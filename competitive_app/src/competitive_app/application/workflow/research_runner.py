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
from typing import Any

from ...domain.research_brief import ResearchBrief
from ...domain.stage import (
    STAGES,
    STAGE_DEPENDENCIES,
    STAGE_OUTPUT_SCHEMA,
    StageResult,
    empty_projection,
    validate_stage_output,
)
from .coverage_engine import CoverageEngine
from .profiles import StageProfile, build_profiles, is_search_tool
from .stage_outputs import append_stage_output, collect_prior_outputs


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
        # Explicit session_id for SOCM path (don't rely on agent.session_id,
        # which is only set inside harness.prompt and stale on resume).
        self._session_id = session_id or getattr(self.agent, "session_id", "") or ""

    async def run(self, start_stage: str | None = None) -> str:
        """Run stages strictly in order. Returns final task status.

        ``start_stage`` (F-R16): if set, stages before it that are already ok
        are skipped. The start_stage itself and everything after runs.
        """
        projection = await self._load_projection()
        start_index = STAGES.index(start_stage) if start_stage else 0

        for index, name in enumerate(STAGES):
            if self.abort_signal.is_set():
                await self._set_status("aborted")
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
            try:
                result = await self._run_stage(name, projection)
            except asyncio.CancelledError:
                self.agent.abort()
                projection["stages"][name] = "failed"
                await self._save_projection(projection)
                await self._set_status("aborted")
                raise
            except Exception as exc:  # noqa: BLE001
                result = StageResult(stage=name, ok=False, output={}, error=f"{type(exc).__name__}: {exc}")
            if not result.ok:
                projection["stages"][name] = "failed"
                await self._save_projection(projection)
                await self._set_status("failed")
                return "failed"
            # Re-load projection: the search stage's CoverageEngine writes
            # `coverage` directly to the store; merge it into our in-memory copy
            # so the final projection preserves coverage (F-R13).
            projection = await self._load_projection()
            projection["stages"][name] = "ok"
            await self._save_projection(projection)

        projection["current_stage"] = None
        await self._save_projection(projection)
        await self._set_status("completed")
        return "completed"

    async def _run_stage(self, name: str, projection: dict[str, Any]) -> StageResult:
        profile = self.profiles[name]

        if name == "search":
            # search delegates to CoverageEngine (no single prompt; iterative loop).
            return await self._run_search_stage(profile)

        # plan / write: per-stage tool filter (F-R8) + single agent.prompt.
        self.agent.state.tools = self._select_tools(profile)
        prior = await collect_prior_outputs(self.session, STAGE_DEPENDENCIES[name])
        prompt = self._build_prompt(name, profile, prior)
        await self.harness.prompt(prompt)
        if self.abort_signal.is_set():
            return StageResult(stage=name, ok=False, output={}, error="aborted")
        output = self._extract_output(name)
        result = validate_stage_output(name, output)
        if result.ok:
            await append_stage_output(self.session, name, output)
        return result

    async def _run_search_stage(self, profile: StageProfile) -> StageResult:
        """Run the search stage via CoverageEngine (F-R31)."""
        prior = await collect_prior_outputs(self.session, STAGE_DEPENDENCIES["search"])
        plan_output = prior.get("plan") or {}
        if not plan_output:
            return StageResult(stage="search", ok=False, output={}, error="missing plan output")
        # Validate plan's coverage_schema (F-R26): ≥1 entity × ≥1 attribute.
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
        )
        search_output = await engine.run(plan_output)
        # Validate + persist the search stage output (F-R10/F-R4).
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

    def _build_prompt(self, name: str, profile: StageProfile, prior: dict[str, Any]) -> str:
        self.agent.state.systemPrompt = profile.system_prompt
        brief = self.research_brief.model_dump(mode="json")
        parts: list[str] = []
        parts.append(f"Research brief: {json.dumps(brief, ensure_ascii=False)}")
        for stage_name, output in prior.items():
            parts.append(f"Prior stage '{stage_name}' output: {json.dumps(output, ensure_ascii=False)}")
        if name == "write":
            # write needs the SOCM coverage snapshot, not just prior stage text.
            parts.append(
                "(The coverage map snapshot with filled/unknown/conflict cells is provided "
                "as a custom_message stage_output from the search stage; render it as a "
                "citation-grounded markdown table.)"
            )
        parts.append(f"Now run the '{name}' stage. Output ONLY the JSON described in the system prompt.")
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
            return merged
        return empty_projection()

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


__all__ = ["ResearchRunner"]
