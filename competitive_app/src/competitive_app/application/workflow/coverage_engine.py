"""Coverage engine — search stage orchestration (research-workflow-v1 v0.2.0).

ADR 0010 D-S8 / F-R31. Drives the iterative coverage-map-driven search loop:
evaluate empty cells → dispatch subtask → sub-agent searches → fill SOCM →
terminate when coverage≥threshold OR budget exhausted OR no progress.

PR3 (Phase B): SERIAL single sub-agent — one subtask at a time, no parallelism.
PR4 (Phase C) will add the asyncio Task pool (SEARCH_MAX_PARALLEL) + Sensor.
PR5 (Phase D) will replace the direct `fill_from_subagent` with judge-based
Extraction (EvidenceIntake). For now, the sub-agent's own evidence list is
mapped into coverage cells directly (so the three-stage path runs end-to-end
without the judge).

The engine reads/writes SOCM via SocmStore.atomic_update (F-R27). The sub-agent
runs on the task's AgentHarness (ephemeral prompts; findings go to SOCM, not
JSONL — F-R28). Mid-search projection updates go to the TaskProjectionStore.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import uuid4

from ...domain.socm import (
    Attribute,
    AttributeType,
    CoverageMap,
    Entity,
    EntityType,
    EvidenceNode,
    SOCMState,
)
from ...domain.socm.coverage import CellStatus
from ...domain.stage import STAGES
from .profiles import is_search_tool

_log = logging.getLogger(__name__)

# Defaults (env-overridable in wiring; engine takes resolved values).
DEFAULT_COVERAGE_THRESHOLD = 0.8
DEFAULT_MAX_ITERATIONS = 10
DEFAULT_MAX_STALLED_ITERATIONS = 3


def _env_int(name: str, default: int) -> int:
    import os

    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    import os

    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class CoverageEngine:
    """Search-stage orchestrator (serial in PR3; parallel in PR4)."""

    def __init__(
        self,
        *,
        socm_store: Any,
        session_id: str,
        harness: Any,
        all_tools: list[Any],
        store: Any,
        task_id: str,
        abort_signal: asyncio.Event,
        coverage_threshold: float | None = None,
        max_iterations: int | None = None,
        max_stalled_iterations: int | None = None,
        pause_event: asyncio.Event | None = None,
    ) -> None:
        self._socm_store = socm_store
        self._session_id = session_id
        self._harness = harness
        self._agent = harness.agent
        self._all_tools = all_tools
        self._store = store
        self._task_id = task_id
        self._abort = abort_signal
        # Bind the agent's session_id too (harness.prompt sets it, but ensure
        # the SOCM path uses the explicit id passed in, not the agent's).
        self._coverage_threshold = coverage_threshold or _env_float(
            "SEARCH_COVERAGE_THRESHOLD", DEFAULT_COVERAGE_THRESHOLD
        )
        self._max_iterations = max_iterations or _env_int("SEARCH_MAX_ITERATIONS", DEFAULT_MAX_ITERATIONS)
        self._max_stalled = max_stalled_iterations or _env_int(
            "SEARCH_MAX_STALLED_ITERATIONS", DEFAULT_MAX_STALLED_ITERATIONS
        )
        # O6 test seam: if set, the engine pauses before the first search iteration.
        self._pause_event = pause_event

    async def run(self, plan_output: dict[str, Any]) -> dict[str, Any]:
        """Run the search loop. Returns the search stage output (evidence + coverage).

        Initializes SOCM from plan's coverage_schema, then loops until a
        termination condition (F-R31). Persists SOCM + updates projection.
        """
        schema = plan_output.get("coverage_schema") or {}
        intent = plan_output.get("plan") or ""

        # F-R16: do NOT overwrite an existing SOCM on resume. If a SOCM already
        # exists for this session (search was interrupted with partial progress),
        # continue from it — filled/unknown cells are preserved, only empty cells
        # get re-dispatched. Only initialize fresh when no SOCM exists yet.
        existing = await self._socm_store.load(self._session_id)
        if existing.coverage_map.filled_count() == 0 and len(existing.coverage_map.cells) == 0:
            coverage_map = _coverage_map_from_schema(schema)
            await self._socm_store.save(
                self._session_id, SOCMState(intent=intent, coverage_map=coverage_map)
            )
        else:
            # Resume: keep existing coverage_map; refresh intent only.
            existing.intent = intent or existing.intent
            await self._socm_store.save(self._session_id, existing)
        await self._update_projection()

        if self._pause_event is not None:
            await self._pause_event.wait()

        stalled = 0
        for iteration in range(1, self._max_iterations + 1):
            if self._abort.is_set():
                break

            state = await self._socm_store.load(self._session_id)
            state.iteration = iteration
            empties = state.coverage_map.empty_cells()
            if not empties:
                break  # nothing left to search

            # Termination 1: coverage threshold met.
            if state.coverage_map.coverage_ratio() >= self._coverage_threshold:
                break

            # Dispatch ONE subtask (serial PR3) — batch empty cells by entity.
            subtask = _build_subtask(empties)
            await self._run_subagent(state, subtask)

            # Re-load to see what got filled.
            after = await self._socm_store.load(self._session_id)
            after.iteration = iteration
            filled_before = state.coverage_map.filled_count()
            filled_after = after.coverage_map.filled_count()

            # Termination 3: no progress.
            if filled_after <= filled_before:
                after.stalled_iterations = state.stalled_iterations + 1
                await self._socm_store.save(self._session_id, after)
                if after.stalled_iterations >= self._max_stalled:
                    _log.info("search stage: no progress for %d iterations, terminating", after.stalled_iterations)
                    break
            else:
                after.stalled_iterations = 0
                await self._socm_store.save(self._session_id, after)

            # Persist budget iteration count.
            latest = await self._socm_store.load(self._session_id)
            latest.budget.consume_iteration()
            await self._socm_store.save(self._session_id, latest)
            await self._update_projection()

            # Termination 2: budget exhausted (check the post-consumption state).
            if latest.budget.exhausted():
                _log.info("search stage: budget exhausted (%s), terminating", latest.budget.exhausted_dim())
                break

        # Final state + projection.
        final = await self._socm_store.load(self._session_id)
        await self._update_projection()
        return {
            "evidence": _evidence_summary(final),
            "coverage": final.coverage_map.to_projection(),
        }

    async def _run_subagent(self, state: SOCMState, subtask: dict[str, Any]) -> None:
        """Run one sub-agent prompt for a subtask, then map findings into SOCM.

        PR3: the sub-agent returns ``{"evidence": [...]}``; we fill cells directly
        from the evidence list. PR5 replaces this with judge-based Extraction.

        Returns implicitly via SOCM mutation. Distinguishes three outcomes:
        - sub-agent ran and returned evidence → fill cells.
        - sub-agent ran and explicitly returned ``{"evidence": []}`` → mark_unknown
          (genuinely searched, found nothing; terminal for re-dispatch).
        - sub-agent prompt raised / was aborted / produced no new message → leave
          cells ``empty`` so they can be re-dispatched next iteration (A2 fix).
        """
        # Filter tools to search tools for this stage (F-R8).
        self._agent.state.tools = [t for t in self._all_tools if is_search_tool(t.name)]
        self._agent.state.systemPrompt = _SEARCH_RUNTIME_PROMPT

        prompt = _build_subagent_prompt(state, subtask)
        # Snapshot message count BEFORE the prompt so we only parse the new
        # assistant message (not historical ones — faux with an empty response
        # queue would otherwise re-read the plan stage's assistant message).
        msg_count_before = len(self._agent.state.messages)
        ran_clean = False
        try:
            await self._harness.prompt(prompt)
            ran_clean = True
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            _log.exception("sub-agent prompt failed for subtask %s", subtask.get("question"))
            return  # leave cells empty (re-dispatchable)

        if self._abort.is_set() or not ran_clean:
            return  # leave cells empty

        # Extract the sub-agent's JSON evidence from the NEW assistant message only.
        # `_extract_evidence` returns None if no new assistant message was produced
        # (distinguishing "ran but said nothing" from "returned explicit []").
        evidence = _extract_evidence(self._agent, msg_count_before)
        await self._fill_socm_from_evidence(state, subtask, evidence)

    async def _fill_socm_from_evidence(
        self, state: SOCMState, subtask: dict[str, Any], evidence: list[dict[str, Any]] | None
    ) -> None:
        """Map sub-agent evidence into SOCM coverage cells (PR3 direct fill).

        PR5 will replace this with judge-based Extraction (EvidenceIntake).
        - ``evidence is None`` → sub-agent produced no new message (transient
          failure); leave cells ``empty`` for re-dispatch.
        - ``evidence == []`` → sub-agent explicitly searched and found nothing;
          ``mark_unknown`` (terminal, won't re-dispatch).
        - ``evidence`` non-empty → fill cells directly (PR5 judge will extract
          proper entity/attribute/value).
        """
        if evidence is None:
            return  # transient failure; leave empty (re-dispatchable)

        if not evidence:
            # Genuinely searched, no evidence found → mark_unknown (terminal).

            def _mark_unknowns(s: SOCMState) -> SOCMState:
                for cell_key in subtask.get("target_cells", []):
                    entity_id, attr_id = cell_key.split(".", 1)
                    s.coverage_map.mark_unknown(entity_id, attr_id)
                return s

            await self._socm_store.atomic_update(self._session_id, _mark_unknowns)
            return

        def _fill(s: SOCMState) -> SOCMState:
            for item in evidence:
                source = str(item.get("source") or "")
                content = str(item.get("content") or "")
                if not content:
                    continue
                # Naive PR3 mapping: try each target cell; fill if content non-empty.
                # (PR5 judge will do proper entity/attribute/value extraction.)
                for cell_key in subtask.get("target_cells", []):
                    entity_id, attr_id = cell_key.split(".", 1)
                    cell = s.coverage_map.get_cell(entity_id, attr_id)
                    if cell is None or cell.status != CellStatus.EMPTY:
                        continue
                    s.evidence_graph.add_node(
                        EvidenceNode(
                            id=f"ev_{uuid4().hex[:8]}",
                            entity=entity_id,
                            attribute=attr_id,
                            value=content,
                            finding=content,
                            source=source,
                            source_excerpt=content[:200],
                            confidence=0.6,
                        )
                    )
                    s.coverage_map.fill(
                        entity_id, attr_id, value=content, source=source, source_excerpt=content[:200], confidence=0.6
                    )
            return s

        await self._socm_store.atomic_update(self._session_id, _fill)

    async def _update_projection(self) -> None:
        state = await self._socm_store.load(self._session_id)
        task = await self._store.get_task(self._task_id)
        if task is None:
            return
        projection = task.get("projection") or {}
        projection["coverage"] = state.coverage_map.to_projection()
        await self._store.update_task_status(self._task_id, task["status"], projection=projection)


# ----------------------------------------------------------------- helpers


def _coverage_map_from_schema(schema: dict[str, Any]) -> CoverageMap:
    """Build an empty CoverageMap from plan's coverage_schema (F-R26)."""
    table_id = schema.get("table_id") or "t_competitive"
    entities = [
        Entity(
            id=e.get("id") or f"e_{e.get('name', '').lower()}",
            name=e.get("name") or "",
            kind=EntityType(e.get("kind")) if e.get("kind") in {"target", "competitor"} else EntityType.COMPETITOR,
        )
        for e in schema.get("entities") or []
    ]
    attributes = []
    for a in schema.get("attributes") or []:
        type_str = str(a.get("type") or "text")
        enum_values: list[str] = []
        if type_str.startswith("enum:"):
            enum_values = [v.strip() for v in type_str[5:].split(",") if v.strip()]
            attr_type = AttributeType.ENUM
        else:
            try:
                attr_type = AttributeType(type_str)
            except ValueError:
                attr_type = AttributeType.TEXT
        attributes.append(
            Attribute(
                id=a.get("id") or f"a_{a.get('name', '').lower()}",
                name=a.get("name") or "",
                dimension=a.get("dimension") or "",
                type=attr_type,
                enum_values=enum_values,
                validation=a.get("validation") or "non_empty",
            )
        )
    return CoverageMap.from_schema(table_id=table_id, entities=entities, attributes=attributes)


def _build_subtask(empty_cells: list[Any]) -> dict[str, Any]:
    """Batch empty cells by entity into one subtask (PR3: single subtask per iteration)."""
    # Group by entity_id.
    by_entity: dict[str, list[str]] = {}
    for cell in empty_cells:
        by_entity.setdefault(cell.entity_id, []).append(f"{cell.entity_id}.{cell.attribute_id}")
    # Pick the entity with the most empty cells (highest leverage).
    entity_id = max(by_entity, key=lambda k: len(by_entity[k]))
    target_cells = by_entity[entity_id]
    return {
        "entity_id": entity_id,
        "target_cells": target_cells,
        "question": f"Fill coverage cells for {entity_id}: {', '.join(target_cells)}",
    }


def _build_subagent_prompt(state: SOCMState, subtask: dict[str, Any]) -> str:
    cells_desc = "\n".join(f"  - {c}" for c in subtask.get("target_cells", []))
    return (
        f"Research intent: {state.intent}\n\n"
        f"Subtask: {subtask.get('question')}\n"
        f"Empty cells to fill (entity.attribute):\n{cells_desc}\n\n"
        f"Use search tools to find evidence, then fetch relevant pages. "
        f"Return JSON: {{\"evidence\": [{{\"source\": \"<url>\", \"content\": \"<finding>\"}}]}}. "
        f"If no evidence found, return {{\"evidence\": []}}."
    )


_SEARCH_RUNTIME_PROMPT = "You are a search sub-agent. Find pages and fetch them to fill coverage cells."


def _extract_evidence(agent: Any, since: int = 0) -> list[dict[str, Any]] | None:
    """Pull the sub-agent's JSON evidence from NEW assistant messages (index >= since).

    Only messages added after the sub-agent prompt began are considered, so a
    faux empty-response queue doesn't re-read prior stages' assistant messages.
    Returns:
      - a list (possibly empty) if a new assistant message was produced.
      - None if no new assistant message exists (transient failure / abort).
    """
    for message in reversed(agent.state.messages[since:]):
        if isinstance(message, dict) and message.get("role") == "assistant":
            text = _message_text(message)
            if not text:
                continue
            parsed = _try_parse_json(text)
            if isinstance(parsed, dict):
                ev = parsed.get("evidence")
                if isinstance(ev, list):
                    return ev
            # Tolerant fallback: stuff raw text as one evidence item.
            return [{"source": "subagent", "content": text}]
    return None


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


def _evidence_summary(state: SOCMState) -> list[dict[str, Any]]:
    return [
        {"source": n.source, "content": n.finding or n.value}
        for n in state.evidence_graph.nodes
    ]


__all__ = [
    "DEFAULT_COVERAGE_THRESHOLD",
    "DEFAULT_MAX_ITERATIONS",
    "DEFAULT_MAX_STALLED_ITERATIONS",
    "CoverageEngine",
]
