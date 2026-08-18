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
from .plan_normalize import normalize_plan_output
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
        search_overrides: dict[str, Any] | None = None,
    ) -> None:
        self._search_overrides = search_overrides or {}
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
        if name == "write":
            # v0.2.6: write is per-section (overview + per-dimension + conclusion).
            return await self._run_write_stage(profile)

        # plan: per-stage tool filter (F-R8) + single agent.prompt.
        self.agent.state.tools = self._select_tools(profile)
        prior = await collect_prior_outputs(self.session, STAGE_DEPENDENCIES[name])
        if self._skill_snapshot is not None:
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
        prompt = self._build_prompt(name, profile, prior)
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
        # v0.2.11: deterministic guardrail — expand aggregate rows into per-item
        # entities (brief-enumerated items), so e.g. per-country policy cells are
        # searched instead of crammed into an umbrella row.
        if name == "plan":
            output = normalize_plan_output(output, self.research_brief.goal or "")
        result = validate_stage_output(name, output)
        if result.ok:
            await append_stage_output(self.session, name, output)
        return result

    async def _run_write_stage(self, profile: StageProfile) -> StageResult:
        """v0.2.6: write per-section — overview + per-dimension + conclusion.

        Replaces the one-shot harness.prompt with N+2 sequential harness.prompt
        calls (one per section) on the main session (D24-persisted + SSE events).
        Each section returns {body, sources}; best-effort per section. Assembles
        {report, sections} preserving the v0.2.2 refine contract.
        """
        self.agent.state.tools = self._select_tools(profile)  # write: no tools
        skills = self._stage_skills.get("write", [])
        base = profile.system_prompt
        if self._skill_composer is not None:
            self.agent.state.systemPrompt = self._skill_composer.compose(base, skills, "write")
        else:
            self.agent.state.systemPrompt = base
        prior = await collect_prior_outputs(self.session, STAGE_DEPENDENCIES["write"])
        memory_blob: str | None = None
        try:
            memory_blob = await recall_prior_findings(
                self.store,
                [self.research_brief.target.name, *self.research_brief.competitors],
            )
        except Exception:  # noqa: BLE001 — best-effort recall; never fail write
            memory_blob = None
        # v0.2.10: 写阶段按任务 prompt 指定的结构组织章节 (report_structure),
        # 否则退回通用 overview/dims/conclusion。
        plan_output = (prior.get("plan") or {}) if isinstance(prior, dict) else {}
        sections_to_write = self._section_list(plan_output)
        t0 = time.monotonic()
        section_results: list[dict[str, Any]] = []
        for _sid, title, focus in sections_to_write:
            await self._emit_event(
                "subagent_start", {"entity": title, "task_id": self.task_id}
            )
            prompt = self._build_section_prompt(title, focus, prior, memory_blob)
            try:
                await self.harness.prompt(prompt)
                body, sources = self._extract_section_output()
            except Exception:  # noqa: BLE001 — best-effort: one section failure ≠ write failure
                body, sources = "(本节生成失败)", []
            section_results.append({"title": title, "body": body, "sources": sources})
            await self._emit_event(
                "subagent_end", {"entity": title, "task_id": self.task_id}
            )
        latency_ms = int((time.monotonic() - t0) * 1000)
        usage = last_usage(self.agent.state.messages)
        await self._emit_event(
            "span",
            {
                "kind": "write",
                "stage": "write",
                "task_id": self.task_id,
                "entity": None,
                "model": model_name(self.agent.state.model),
                "prompt_tokens": int(usage.get("input", 0) or 0),
                "completion_tokens": int(usage.get("output", 0) or 0),
                "latency_ms": latency_ms,
            },
        )
        if self.abort_signal.is_set():
            return StageResult(stage="write", ok=False, output={}, error="aborted")
        report_md, sections_out = _assemble_report(section_results)
        output = {"report": report_md, "sections": sections_out}
        result = validate_stage_output("write", output)
        if result.ok:
            await append_stage_output(self.session, "write", output)
        return result

    def _section_list(self, plan_output: dict[str, Any] | None = None) -> list[tuple[str, str, str]]:
        """Sections to write.

        v0.2.10: 按任务要求的结构组织章节。优先级:
        1. plan 的 ``report_structure``（LLM 从 prompt 提取, 可能缺失）;
        2. 从 research brief 程序化提取 (编号的 ``**粗体标题**`` 章节/表格);
        3. 退回 v0.2.6 通用 overview + per-dimension + conclusion。
        DRB II 报告轨按 brief 明确指定的章节/表格判分, 因此 1/2 都要精确保留标题。
        """
        structure = (plan_output or {}).get("report_structure") if plan_output else None
        if isinstance(structure, list) and structure:
            sections: list[tuple[str, str, str]] = []
            for i, item in enumerate(structure):
                if not isinstance(item, dict):
                    continue
                title = str(item.get("section") or item.get("title") or f"Section {i + 1}")
                focus = str(item.get("focus") or "")
                sections.append((f"struct:{i}", title, focus))
            if sections:
                return sections
        brief_structure = _extract_report_structure_from_brief(self.research_brief.goal or "")
        if brief_structure:
            return brief_structure
        dims = list(self.research_brief.dimensions or [])
        sections = [
            (
                "overview",
                "概述",
                "Background + key findings summary across all entities/dimensions.",
            )
        ]
        for d in dims:
            sections.append((f"dim:{d}", d, f"Focus on cells relevant to the dimension 「{d}」."))
        sections.append(
            ("conclusion", "结论与建议", "Synthesize findings + give actionable recommendations.")
        )
        return sections

    def _build_section_prompt(
        self, title: str, focus: str, prior: dict[str, Any], memory_blob: str | None
    ) -> str:
        brief = self.research_brief.model_dump(mode="json")
        parts: list[str] = [f"Research brief: {json.dumps(brief, ensure_ascii=False)}"]
        for stage_name, output in prior.items():
            parts.append(
                f"Prior stage '{stage_name}' output: {json.dumps(output, ensure_ascii=False)}"
            )
        if memory_blob:
            parts.append(memory_blob)
        parts.append(f"Write the section: 「{title}」. {focus}")
        parts.append(
            'Output ONLY valid JSON: {"body": "<markdown section body>", '
            '"sources": [{"n":1,"url":"<url>","label":"<short label>"}]}.'
        )
        return "\n\n".join(parts)

    def _extract_section_output(self) -> tuple[str, list[dict[str, Any]]]:
        """Parse {body, sources} from the last assistant message (tolerant fallback)."""
        for message in reversed(self.agent.state.messages):
            if isinstance(message, dict) and message.get("role") == "assistant":
                text = _message_text(message)
                if not text:
                    continue
                parsed = _try_parse_json(text)
                if isinstance(parsed, dict) and str(parsed.get("body") or "").strip():
                    sources = parsed.get("sources") or []
                    if not isinstance(sources, list):
                        sources = []
                    return str(parsed["body"]).strip(), sources
                return text.strip(), []  # fallback: raw text as body
        return "", []

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
            # v0.2.7: per-task search hyperparameter overrides (POST /tasks search_overrides).
            max_parallel=self._search_overrides.get("max_parallel"),
            coverage_threshold=self._search_overrides.get("coverage_threshold"),
            max_queries=self._search_overrides.get("max_queries"),
            max_wall_seconds=self._search_overrides.get("max_wall_seconds"),
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


def _extract_report_structure_from_brief(
    goal: str,
) -> list[tuple[str, str, str]] | None:
    """从 brief 显式结构提取章节 (编号的 ``**粗体标题**`` 列表)。

    v0.2.10 兜底：plan LLM 可能漏报 ``report_structure``，但 DRB II 任务通常
    在 prompt 里明确编号章节/表格（``1. **Cost Data Compilation...**: ...``）。
    此模式最可靠；无命中 -> None（退回通用结构）。
    """
    import re

    sections: list[tuple[str, str, str]] = []
    for m in re.finditer(
        r"(?m)^\s*(\d+)[.)]\s*\*\*(.+?)\*\*\s*[:：]?\s*(.*)$", goal
    ):
        title = m.group(2).strip()
        focus = m.group(3).strip()
        if title:
            sections.append((f"struct:{len(sections)}", title, focus))
    return sections if sections else None


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


def _assemble_report(
    section_results: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """v0.2.6: assemble per-section {title, body, sources} into (report, sections).

    report = ``## {title}\\n{body}`` per section + a ``## Sources`` block grouped by
    section (no global [n] renumber). sections = [{id, title, body}] with the
    ``## {title}`` heading inside body (matches _split_sections shape so refine +
    ReportPage work identically whether sections were split or generated).
    """
    report_parts: list[str] = []
    sections: list[dict[str, Any]] = []
    sources_parts: list[str] = []
    idx = 0
    for sr in section_results:
        idx += 1
        title = str(sr.get("title") or f"Section {idx}")
        body = str(sr.get("body") or "")
        section_md = f"## {title}\n{body}".strip()
        report_parts.append(section_md)
        sections.append({"id": str(idx), "title": title, "body": section_md})
        srcs = sr.get("sources") or []
        if isinstance(srcs, list) and srcs:
            lines = [f"### {title}"]
            for s in srcs:
                if isinstance(s, dict):
                    n = s.get("n", "")
                    url = s.get("url", "")
                    label = s.get("label", "")
                    lines.append(f"[{n}] {url}" + (f" — {label}" if label else ""))
                else:
                    lines.append(str(s))
            sources_parts.append("\n".join(lines))
    idx += 1
    sources_body = "\n\n".join(sources_parts) if sources_parts else "(无来源)"
    sources_md = f"## Sources\n{sources_body}"
    report_parts.append(sources_md)
    sections.append({"id": str(idx), "title": "Sources", "body": sources_md})
    return "\n\n".join(report_parts), sections


async def _noop_emit(_event_type: str, _data: dict[str, Any]) -> None:
    """v0.3.1 SSE: default emit sink (no-op when SSE isn't wired)."""
    return


__all__ = ["ResearchRunner"]
