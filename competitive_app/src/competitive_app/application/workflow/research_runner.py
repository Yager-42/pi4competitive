"""Three-stage research runner (research-workflow-v1 v0.2.0 F-R25/F-R31).

Replaces the v0.1.1 six-stage runner. Runs STAGES=(plan, search, write) in
strict order with dependency/input gates (F-R3). The search stage delegates to
CoverageEngine (ADR 0010 D-S8) which drives the iterative coverage-map search
loop and persists SOCM. plan/write run a single agent.prompt each.

v0.1.1 behaviors preserved: dependency gating, per-stage tool filtering (F-R8),
context-derived data passing (F-R9), minimal-schema output validation (F-R10),
SQLite projection updates (F-R13), resume skipping ok stages (F-R16), and
double-layer abort (F-R21).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ...domain.research_brief import ResearchBrief
from ...domain.stage import (
    STAGE_DEPENDENCIES,
    STAGE_OUTPUT_SCHEMA,
    STAGES,
    StageResult,
    empty_projection,
    validate_stage_output,
)
from .coverage_engine import CoverageEngine
from .memory_inject import recall_prior_findings
from .profiles import StageProfile, build_profiles, is_search_tool
from .stage_outputs import append_stage_output, collect_prior_outputs, last_usage, model_name


def _noop_journal_append(_event_type: str, _payload: dict[str, Any] | None = None) -> None:
    """Default journal sink (no-op when observability isn't wired)."""
    return


class ResearchRunner:
    def __init__(
        self,
        *,
        task_id: str,
        harness: Any,
        session: Any,
        store: Any,
        socm_store: Any,
        research_brief: ResearchBrief,
        all_tools: list[Any],
        profiles: dict[str, StageProfile] | None = None,
        abort_signal: asyncio.Event | None = None,
        coverage_engine: CoverageEngine | None = None,
        session_id: str | None = None,
        subagent_factory: Any = None,
        judge_model: dict[str, Any] | None = None,
        emit_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        journal_append: Callable[[str, dict[str, Any]], None] | None = None,
        skill_snapshot: Any = None,
        skill_composer: Any = None,
    ) -> None:
        self.task_id = task_id
        self.harness = harness
        self.agent = harness.agent
        self.session = session
        self.store = store
        self.socm_store = socm_store
        self.research_brief = research_brief
        self.all_tools = all_tools
        self.profiles = profiles or build_profiles()
        self.abort_signal = abort_signal or asyncio.Event()
        self._coverage_engine = coverage_engine
        self._subagent_factory = subagent_factory
        self._judge_model = judge_model
        self._emit_event = emit_event or _noop_emit
        self._journal_append = journal_append or _noop_journal_append
        self._session_id = session_id or getattr(self.agent, "session_id", "") or ""
        self._skill_snapshot = skill_snapshot
        self._skill_composer = skill_composer
        self._stage_skills: dict[str, list[Any]] = {}

    async def run(
        self,
        start_stage: str | None = None,
        stop_after_stage: str | None = None,
    ) -> str:
        """Run stages strictly in order. Returns final task status.

        ``start_stage`` (F-R16): if set, stages before it that are already ok
        are skipped. The start_stage itself and everything after runs.

        ``stop_after_stage`` (experiment harness): if set, run stages up to and
        INCLUDING this stage, then stop (subsequent stages stay pending). Used by
        the three-vs-six comparison to measure search-only quality without the
        cost of the write/analyze stages. Task is marked completed.
        """
        projection = await self._load_projection()
        start_index = STAGES.index(start_stage) if start_stage else 0

        for index, name in enumerate(STAGES):
            if self.abort_signal.is_set():
                await self._set_status("aborted")
                await self._emit_event(
                    "error",
                    {"task_id": self.task_id, "status": "aborted", "message": "aborted by signal"},
                )
                return "aborted"
            if index < start_index:
                if projection["stages"].get(name) == "ok":
                    continue
            # Dependency gate (F-R3).
            for dep in STAGE_DEPENDENCIES[name]:
                if projection["stages"].get(dep) != "ok":
                    projection["stages"][name] = "failed"
                    projection["current_stage"] = name
                    await self._save_projection(projection)
                    await self._set_status("failed")
                    return "failed"
            projection["current_stage"] = name
            projection["stages"][name] = "running"
            await self._save_projection(projection)
            await self._emit_event("stage_start", {"stage": name, "task_id": self.task_id})
            try:
                result = await self._run_stage(name, projection)
            except asyncio.CancelledError:
                self.agent.abort()
                projection["stages"][name] = "failed"
                await self._save_projection(projection)
                await self._set_status("aborted")
                await self._emit_event(
                    "error",
                    {
                        "task_id": self.task_id,
                        "status": "aborted",
                        "stage": name,
                        "message": "cancelled",
                    },
                )
                raise
            except Exception as exc:  # noqa: BLE001
                result = StageResult(
                    stage=name, ok=False, output={}, error=f"{type(exc).__name__}: {exc}"
                )
            if not result.ok:
                projection["stages"][name] = "failed"
                await self._save_projection(projection)
                await self._emit_event(
                    "stage_end",
                    {"stage": name, "ok": False, "task_id": self.task_id, "error": result.error},
                )
                await self._set_status("failed")
                await self._emit_event(
                    "error",
                    {
                        "task_id": self.task_id,
                        "status": "failed",
                        "stage": name,
                        "message": result.error or "",
                    },
                )
                return "failed"
            # Re-load projection: the search stage's CoverageEngine writes
            # `coverage` directly to the store; merge it into our in-memory copy
            # so the final projection preserves coverage (F-R13).
            projection = await self._load_projection()
            projection["stages"][name] = "ok"
            await self._save_projection(projection)
            await self._emit_event(
                "stage_end", {"stage": name, "ok": True, "task_id": self.task_id}
            )
            # write stage done → report ready (report_id = task_id, v0.3.1-A decision 1).
            if name == "write":
                await self._emit_event(
                    "report_ready", {"report_id": self.task_id, "task_id": self.task_id}
                )
                self._journal_append(
                    "report.generated",
                    {"report_id": self.task_id, "task_id": self.task_id},
                )
            # Experiment harness: stop after the named stage (search/collect) without
            # running downstream stages. Mark completed — the search stage is what we
            # wanted to measure.
            if stop_after_stage and name == stop_after_stage:
                projection["current_stage"] = None
                await self._fill_report_card_fields(projection)
                await self._save_projection(projection)
                await self._set_status("completed")
                await self._emit_event("done", {"task_id": self.task_id, "status": "completed"})
                return "completed"

        projection["current_stage"] = None
        await self._fill_report_card_fields(projection)
        await self._save_projection(projection)
        await self._set_status("completed")
        await self._emit_event("done", {"task_id": self.task_id, "status": "completed"})
        return "completed"

    async def _run_stage(self, name: str, projection: dict[str, Any]) -> StageResult:
        profile = self.profiles[name]

        if name == "search":
            # search delegates to CoverageEngine (no single prompt; iterative loop).
            return await self._run_search_stage(profile)

        # plan / write: per-stage tool filter (F-R8) + single agent.prompt.
        self.agent.state.tools = self._select_tools(profile)
        prior = await collect_prior_outputs(self.session, STAGE_DEPENDENCIES[name])
        if self._skill_snapshot is not None and name in {"plan", "write"}:
            description = self.research_brief.model_dump_json()
            self._stage_skills[name] = await self._skill_snapshot.ensure_scope(
                self.task_id, name, description
            )
            self._journal_append(
                "skill.select",
                {
                    "stage": name,
                    "skills": [s.skill_id or s.name for s in self._stage_skills[name]],
                    "task_id": self.task_id,
                },
            )
        memory_blob: str | None = None
        if name == "write":
            try:
                memory_blob = await recall_prior_findings(
                    self.store,
                    [self.research_brief.target.name, *self.research_brief.competitors],
                )
            except Exception:  # noqa: BLE001 — best-effort recall; never fail the write stage
                memory_blob = None
        prompt = self._build_prompt(name, profile, prior, memory_blob=memory_blob)
        t0 = time.monotonic()
        await self.harness.prompt(prompt)
        latency_ms = int((time.monotonic() - t0) * 1000)
        usage = last_usage(self.agent.state.messages)
        await self._emit_event(
            "span",
            {
                "kind": name,
                "stage": name,
                "task_id": self.task_id,
                "entity": None,
                "model": model_name(self.agent.state.model),
                "prompt_tokens": int(usage.get("input", 0) or 0),
                "completion_tokens": int(usage.get("output", 0) or 0),
                "latency_ms": latency_ms,
            },
        )
        if self.abort_signal.is_set():
            return StageResult(stage=name, ok=False, output={}, error="aborted")
        output = self._extract_output(name)
        result = validate_stage_output(name, output)
        if result.ok:
            # v0.2.2: write stage — derive sections from the markdown (refine support).
            if name == "write":
                output["sections"] = _split_sections(output.get("report") or "")
            await append_stage_output(self.session, name, output)
        return result

    async def _run_search_stage(self, profile: StageProfile) -> StageResult:
        """Run search via CoverageEngine, binding search + extraction once."""
        prior = await collect_prior_outputs(self.session, STAGE_DEPENDENCIES["search"])
        plan_output = prior.get("plan") or {}
        if not plan_output:
            return StageResult(stage="search", ok=False, output={}, error="missing plan output")
        schema = plan_output.get("coverage_schema") or {}
        entities = schema.get("entities") or []
        attributes = schema.get("attributes") or []
        if not entities or not attributes:
            return StageResult(
                stage="search",
                ok=False,
                output={},
                error="plan output missing coverage_schema with ≥1 entity × ≥1 attribute",
            )
        description = json.dumps(plan_output, ensure_ascii=False)
        if self._skill_snapshot is not None:
            self._stage_skills["search"] = await self._skill_snapshot.ensure_scope(
                self.task_id, "search", description
            )
            self._stage_skills["extraction"] = await self._skill_snapshot.ensure_scope(
                self.task_id, "extraction", description
            )
            for stage in ("search", "extraction"):
                self._journal_append(
                    "skill.select",
                    {
                        "stage": stage,
                        "skills": [s.skill_id or s.name for s in self._stage_skills[stage]],
                        "task_id": self.task_id,
                    },
                )
        engine = self._coverage_engine or CoverageEngine(
            socm_store=self.socm_store,
            session_id=self._session_id,
            harness=self.harness,
            all_tools=self.all_tools,
            store=self.store,
            task_id=self.task_id,
            abort_signal=self.abort_signal,
            subagent_factory=self._subagent_factory,
            judge_model=self._judge_model,
            emit_event=self._emit_event,
            journal_append=self._journal_append,
            search_skills=self._stage_skills.get("search", []),
            extraction_skills=self._stage_skills.get("extraction", []),
            skill_composer=self._skill_composer,
        )
        search_output = await engine.run(plan_output)
        result = validate_stage_output("search", search_output)
        if result.ok:
            await append_stage_output(self.session, "search", search_output)
        return result

    def _select_tools(self, profile: StageProfile) -> list[Any]:
        if profile.tool_names is None:
            return [t for t in self.all_tools if is_search_tool(t.name)]
        if not profile.tool_names:
            return []
        wanted = set(profile.tool_names)
        return [t for t in self.all_tools if t.name in wanted]

    def _build_prompt(
        self,
        name: str,
        profile: StageProfile,
        prior: dict[str, Any],
        *,
        memory_blob: str | None = None,
    ) -> str:
        skills = self._stage_skills.get(name, [])
        base = profile.system_prompt
        if self._skill_composer is not None:
            self.agent.state.systemPrompt = self._skill_composer.compose(base, skills, name)
        else:
            self.agent.state.systemPrompt = base
        brief = self.research_brief.model_dump(mode="json")
        parts: list[str] = [f"Research brief: {json.dumps(brief, ensure_ascii=False)}"]
        for stage_name, output in prior.items():
            parts.append(
                f"Prior stage '{stage_name}' output: {json.dumps(output, ensure_ascii=False)}"
            )
        if name == "write":
            parts.append(
                "(The coverage map snapshot with filled/unknown/conflict cells is provided "
                "as a custom_message stage_output from the search stage; render it as a "
                "citation-grounded markdown table.)"
            )
            if memory_blob:
                parts.append(memory_blob)
        parts.append(
            f"Now run the '{name}' stage. Output ONLY the JSON described in the system prompt."
        )
        return "\n\n".join(parts)

    def _extract_output(self, name: str) -> dict[str, Any]:
        """Extract the JSON output from the agent's last assistant message (F-R10).

        Tolerant fallback: wrap raw text in the stage's primary field so the
        stage still passes (the model doesn't always emit strict JSON).
        """
        for message in reversed(self.agent.state.messages):
            if isinstance(message, dict) and message.get("role") == "assistant":
                text = _message_text(message)
                if text:
                    parsed = _try_parse_json(text)
                    if isinstance(parsed, dict):
                        return parsed
                required = STAGE_OUTPUT_SCHEMA.get(name, {"raw"})
                primary = next(iter(required))
                return {primary: text}
        return {}

    async def _load_projection(self) -> dict[str, Any]:
        task = await self.store.get_task(self.task_id)
        if task and isinstance(task.get("projection"), dict):
            existing = task["projection"]
            merged = empty_projection()
            merged["current_stage"] = existing.get("current_stage")
            for name in STAGES:
                merged["stages"][name] = existing.get("stages", {}).get(name, "pending")
            merged["coverage"] = existing.get("coverage", merged["coverage"])
            # v0.3.1 report card fields — merge so resume doesn't lose them.
            merged["report_title"] = existing.get("report_title", merged["report_title"])
            merged["brands"] = existing.get("brands", merged["brands"])
            merged["evidence_count"] = existing.get("evidence_count", merged["evidence_count"])
            merged["claim_count"] = existing.get("claim_count", merged["claim_count"])
            return merged
        return empty_projection()

    async def _fill_report_card_fields(self, projection: dict[str, Any]) -> dict[str, Any]:
        """v0.3.1: populate report card fields on task completion.

        - report_title: first `# ...` line of the write stage markdown, fallback to
          the brief display title. None when write didn't run (stop_after=search).
        - brands: [brief.target.name] + brief.competitors, de-duped preserving order.
        - evidence_count: SOCM evidence_graph node count (judge-extracted findings).
        - claim_count: SOCM coverage_map filled cell count (settled claims).

        Tolerant: any step may fail (no write output, no SOCM) — fields stay at
        their empty_projection defaults rather than raising.
        """
        # brands — from the brief, always available.
        brands = list(
            dict.fromkeys([self.research_brief.target.name] + list(self.research_brief.competitors))
        )
        projection["brands"] = brands

        # evidence_count / claim_count — from SOCM (search SoT).
        try:
            socm = await self.socm_store.load(self._session_id)
            projection["evidence_count"] = socm.evidence_graph.node_count()
            projection["claim_count"] = socm.coverage_map.filled_count()
            # v0.3.3: flatten ACTIVE evidence into the global evidences table
            # (projection; SOCM JSON stays the search SoT, D-S4). Reuses the same
            # socm load — no extra IO. Fails soft: indexing must never break completion.
            task = await self.store.get_task(self.task_id)
            created_at = (task or {}).get("created_at", "")
            await self.store.index_evidences(self.task_id, socm.evidence_graph.nodes, created_at)
        except Exception:  # noqa: BLE001
            pass  # keep defaults (0)

        # report_title — from write stage markdown first `# ` line, fallback query.
        try:
            prior = await collect_prior_outputs(self.session, ("write",))
            write_out = prior.get("write") or {}
            markdown = write_out.get("report") or ""
            title = _extract_report_title(markdown)
            projection["report_title"] = title or self.research_brief.target.name
        except Exception:  # noqa: BLE001
            projection["report_title"] = self.research_brief.target.name
        return projection

    async def _save_projection(self, projection: dict[str, Any]) -> None:
        await self.store.update_task_status(
            self.task_id,
            status="running",
            projection=projection,
        )

    async def _set_status(self, status: str) -> None:
        await self.store.update_task_status(self.task_id, status)


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                chunks.append(str(block.get("text") or ""))
        return "".join(chunks)
    return ""


def _try_parse_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                return None
        return None


def _extract_report_title(markdown: str) -> str:
    """v0.3.1: pull the report title from the write stage markdown.

    Takes the first `# ...` heading line, strips the leading `#`/spaces. Returns
    "" when no heading is found (caller falls back to the brief display title).
    """
    if not markdown:
        return ""
    for line in markdown.lstrip().splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def _split_sections(markdown: str) -> list[dict[str, Any]]:
    """v0.2.2: split a report markdown into sections by `##` headings.

    Each section: {id: "1"/"2"/..., title, body}. `body` is the full text from
    the `##` heading line up to (not including) the next `##` (or end). Top-level
    `#` headings (the report title) are NOT sections — they're skipped, content
    before the first `##` is dropped (it's the title + intro, captured by title).

    Sections are a *derived* view of `report` (the LLM only outputs `report`);
    the runner fills this so refine can locate a section by id. `## Sources` is
    kept as a section so the citation block is refinable too.
    """
    if not markdown:
        return []
    sections: list[dict[str, Any]] = []
    current: list[str] | None = None  # lines of the current section (None = before first ##)
    for line in markdown.splitlines():
        if line.lstrip().startswith("## "):
            # start a new section
            if current is not None:
                sections.append(_finalize_section(current))
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        sections.append(_finalize_section(current))
    # assign sequential ids
    for i, s in enumerate(sections, 1):
        s["id"] = str(i)
    return sections


def _finalize_section(lines: list[str]) -> dict[str, Any]:
    """Build a section dict from its lines (first line is the `##` heading)."""
    heading = lines[0].lstrip().lstrip("#").strip()
    body = "\n".join(lines).strip()
    return {"id": "", "title": heading, "body": body}


async def _noop_emit(_event_type: str, _data: dict[str, Any]) -> None:
    """v0.3.1 SSE: default emit sink (no-op when SSE isn't wired)."""
    return


__all__ = ["ResearchRunner"]
