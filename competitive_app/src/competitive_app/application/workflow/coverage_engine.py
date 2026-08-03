"""Coverage engine — search stage orchestration (research-workflow-v1 v0.2.0).

ADR 0010 D-S8 / F-R31. Drives the iterative coverage-map-driven search loop:
evaluate empty cells → dispatch subtask → sub-agent searches → fill SOCM →
terminate when coverage≥threshold OR budget exhausted OR no progress.

Parallel dispatch (PR4): asyncio Task pool (SEARCH_MAX_PARALLEL) + FIRST_COMPLETED
reap. Each sub-agent runs on a fresh ephemeral harness (F-R28). The Extraction
extension (PR5) hooks ``tool_result`` on ``*_fetch`` tools; the judge LLM
extracts (entity, attribute, value, source, confidence) into SOCM at sub-agent
exit (intake.flush drain point).

The engine reads/writes SOCM via SocmStore.atomic_update (F-R27). The sub-agent
runs on the task's AgentHarness (ephemeral prompts; findings go to SOCM, not
JSONL — F-R28). Mid-search projection updates go to the TaskProjectionStore.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from uuid import uuid4

from ...domain.socm import (
    Attribute,
    AttributeType,
    CoverageMap,
    Entity,
    EntityType,
    SOCMState,
)
from .extraction import current_subtask
from .profiles import is_search_tool
from .stage_outputs import last_usage, model_name

_log = logging.getLogger(__name__)


async def _noop_emit(_event_type: str, _data: dict[str, Any]) -> None:
    """v0.3.1 SSE: default emit sink (no-op when SSE isn't wired)."""
    return


def _noop_journal_append(_event_type: str, _payload: dict[str, Any] | None = None) -> None:
    """Default journal sink (no-op when observability isn't wired)."""
    return


# Defaults (env-overridable in wiring; engine takes resolved values).
DEFAULT_COVERAGE_THRESHOLD = 0.8
DEFAULT_MAX_ITERATIONS = 10
DEFAULT_MAX_STALLED_ITERATIONS = 3
DEFAULT_MAX_PARALLEL = 4
DEFAULT_MAX_CELL_ATTEMPTS = 2
DEFAULT_SUBTASK_CHUNK = 3


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
        max_parallel: int | None = None,
        max_cell_attempts: int | None = None,
        subtask_chunk: int | None = None,
        pause_event: asyncio.Event | None = None,
        subagent_factory: Any = None,
        judge_model: dict[str, Any] | None = None,
        emit_event: Any = None,
        journal_append: Any = None,
        search_skills: list[Any] | None = None,
        extraction_skills: list[Any] | None = None,
        skill_composer: Any = None,
    ) -> None:
        self._socm_store = socm_store
        self._session_id = session_id
        self._harness = harness
        self._agent = harness.agent
        self._all_tools = all_tools
        self._store = store
        self._task_id = task_id
        self._abort = abort_signal
        self._coverage_threshold = coverage_threshold or _env_float(
            "SEARCH_COVERAGE_THRESHOLD", DEFAULT_COVERAGE_THRESHOLD
        )
        self._max_iterations = max_iterations or _env_int("SEARCH_MAX_ITERATIONS", DEFAULT_MAX_ITERATIONS)
        self._max_stalled = max_stalled_iterations or _env_int(
            "SEARCH_MAX_STALLED_ITERATIONS", DEFAULT_MAX_STALLED_ITERATIONS
        )
        self._max_parallel = max_parallel or _env_int("SEARCH_MAX_PARALLEL", DEFAULT_MAX_PARALLEL)
        # Tier-0/1: per-cell re-search budget (weak/junk → re-dispatch up to N times).
        self._max_cell_attempts = max_cell_attempts or _env_int(
            "SEARCH_MAX_CELL_ATTEMPTS", DEFAULT_MAX_CELL_ATTEMPTS
        )
        # Tier-2b: split each entity's actionable cells into chunks of this size so
        # the parallel pool can fill max_parallel even with few entities.
        self._subtask_chunk = subtask_chunk or _env_int("SEARCH_SUBTASK_CHUNK", DEFAULT_SUBTASK_CHUNK)
        # O6 test seam: if set, the engine pauses before the first search iteration.
        self._pause_event = pause_event
        # Factory for ephemeral sub-agent harnesses (PR4 parallel). If None,
        # the engine falls back to running sub-agents serially on the main
        # Factory for ephemeral parallel sub-agents.
        self._subagent_factory = subagent_factory
        self._judge_model = judge_model
        self._emit_event = emit_event or _noop_emit
        self._journal_append = journal_append or _noop_journal_append
        self._search_skills = list(search_skills or [])[:3]
        self._extraction_skills = list(extraction_skills or [])[:3]
        self._skill_composer = skill_composer

    async def run(self, plan_output: dict[str, Any]) -> dict[str, Any]:
        """Run the search loop. Returns the search stage output (evidence + coverage).

        Initializes SOCM from plan's coverage_schema, then loops until a
        termination condition (F-R31). Persists SOCM + updates projection.
        """
        schema = plan_output.get("coverage_schema") or {}
        intent = plan_output.get("plan") or ""
        # Tier-2a: parse the plan's per-entity typed queries + authoritative source
        # hints. Injected into each subtask so sub-agents use targeted queries instead
        # of bare "fill these cells" prompts (root cause of hitting weak aggregator pages).
        self._plan_queries = _parse_plan_queries(plan_output)

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
            # Tier-0/1 (ADR 0010 D-S8 fix): dispatch the ACTIONABLE set, not just EMPTY
            # cells. Actionable = EMPTY + retryable-UNKNOWN + retryable-weak-FILLED, so a
            # cell that got a junk/low-confidence value (→ mark_unknown) or a weak fill
            # gets re-searched instead of locking the loop into a one-round exit.
            actionable = state.coverage_map.actionable_cells(self._max_cell_attempts)
            if not actionable:
                break  # nothing left worth searching

            # Termination 1: satisfied-ratio threshold met (replaces coverage_ratio,
            # which counted junk FILLED as covered and caused premature exit).
            if state.coverage_map.satisfied_ratio(self._max_cell_attempts) >= self._coverage_threshold:
                break

            # Termination 2: budget exhausted (checked before dispatching more).
            if state.budget.exhausted():
                _log.info("search stage: budget exhausted (%s), terminating", state.budget.exhausted_dim())
                break

            # Dispatch subtasks in PARALLEL (PR4): batch actionable cells by entity +
            # chunk (Tier-2b), spawn up to max_parallel sub-agents, reap with FIRST_COMPLETED.
            subtasks = _build_subtasks(actionable, self._max_parallel, self._subtask_chunk)
            # Tier-2a: inject per-entity typed queries + source hints from the plan.
            for st in subtasks:
                qinfo = self._plan_queries.get(st.get("entity_id", ""))
                if qinfo:
                    st["queries"] = qinfo.get("queries") or []
                    st["source_hints"] = qinfo.get("source_hints") or []
            await self._emit_event(
                "iteration_start",
                {"iteration": iteration, "actionable_count": len(actionable),
                 "subtasks": len(subtasks), "task_id": self._task_id},
            )
            satisfied_before = state.coverage_map.satisfied_ratio(self._max_cell_attempts)
            await self._dispatch_parallel(state, subtasks)

            # Re-load to see what got satisfied.
            after = await self._socm_store.load(self._session_id)
            after.iteration = iteration
            satisfied_after = after.coverage_map.satisfied_ratio(self._max_cell_attempts)
            # v0.3.1 SSE: coverage_update after each iteration's dispatch round.
            await self._emit_event(
                "coverage_update",
                {"iteration": iteration, **after.coverage_map.to_projection_with_states(),
                 "task_id": self._task_id},
            )

            # Termination 3: no progress (satisfied-ratio stalled, not just filled-count).
            if satisfied_after <= satisfied_before:
                after.stalled_iterations = state.stalled_iterations + 1
                await self._socm_store.save(self._session_id, after)
                if after.stalled_iterations >= self._max_stalled:
                    _log.info("search stage: no progress for %d iterations, terminating", after.stalled_iterations)
                    self._journal_append(
                        "help.exhausted",
                        {"dimension": "stall", "task_id": self._task_id},
                    )
                    break
            else:
                after.stalled_iterations = 0
                await self._socm_store.save(self._session_id, after)

            # Persist budget iteration count (one per outer-loop round).
            latest = await self._socm_store.load(self._session_id)
            latest.budget.consume_iteration()
            await self._socm_store.save(self._session_id, latest)
            self._journal_append(
                "budget",
                {
                    "kind": "iteration",
                    "iteration": latest.budget.consumed_iterations,
                    "exhausted": latest.budget.exhausted(),
                    "task_id": self._task_id,
                },
            )


            if latest.budget.exhausted():
                _log.info("search stage: budget exhausted (%s), terminating", latest.budget.exhausted_dim())
                self._journal_append(
                    "help.exhausted",
                    {"dimension": "budget", "task_id": self._task_id},
                )
                break

        # Final state + projection.
        final = await self._socm_store.load(self._session_id)
        await self._update_projection()
        return {
            "evidence": _evidence_summary(final),
            "coverage": final.coverage_map.to_projection(),
        }

    async def _dispatch_parallel(self, state: SOCMState, subtasks: list[dict[str, Any]]) -> None:
        """Spawn sub-agents in parallel (PR4) — up to max_parallel concurrent.

        Each sub-agent runs on a fresh ephemeral AgentHarness (InMemorySessionRepo,
        F-R28 — findings go to SOCM, not JSONL). Uses asyncio.wait(FIRST_COMPLETED)
        to reap as soon as any finishes, so new subtasks can fill freed slots.
        Pattern mirrors SearchOS scheduler.py (task_pool + _running_count cap).
        """
        if not subtasks:
            return

        # Pre-consume query/fetch budget for the subtasks we're about to dispatch
        # (Sensor role, PR4 engine-layer): each subtask costs 1 query budget.
        # PR5 will move fine-grained per-tool counting into a Sensor extension.
        for _subtask in subtasks:
            await self._consume_query_budget()

        pool: dict[str, asyncio.Task[Any]] = {}
        queue = list(subtasks)

        async def _spawn_one(subtask: dict[str, Any]) -> str:
            label = f"sub_{uuid4().hex[:8]}"
            await self._emit_event(
                "subagent_start",
                {"entity": subtask.get("entity_id", ""), "cells": subtask.get("target_cells", []),
                 "label": label, "task_id": self._task_id},
            )
            task = asyncio.create_task(
                self._run_subagent_ephemeral(subtask), name=f"search:{label}"
            )
            pool[label] = task
            return label

        # Initial fill up to max_parallel.
        while queue and len(pool) < self._max_parallel:
            await _spawn_one(queue.pop(0))

        # Reap with FIRST_COMPLETED; refill slots as they free.
        while pool:
            if self._abort.is_set():
                for t in pool.values():
                    t.cancel()
                # Await cancellation so a sub-agent mid-atomic_update finishes
                # its RMW before the engine moves on (no post-abort SOCM writes).
                await asyncio.gather(*pool.values(), return_exceptions=True)
                pool.clear()
                break
            done, _pending = await asyncio.wait(
                pool.values(), return_when=asyncio.FIRST_COMPLETED
            )
            # Re-check abort after reaping (observe promptly when a sub-agent finishes).
            if self._abort.is_set():
                for t in pool.values():
                    if not t.done():
                        t.cancel()
                await asyncio.gather(*pool.values(), return_exceptions=True)
                pool.clear()
                break
            # Reap every completed task (SearchOS whole-pool reap pattern).
            finished_labels = [lbl for lbl, t in pool.items() if t.done()]
            for lbl in finished_labels:
                pool.pop(lbl, None)
            # Refill from queue.
            while queue and len(pool) < self._max_parallel:
                await _spawn_one(queue.pop(0))

    async def _consume_query_budget(self) -> None:
        """Decrement the queries budget dimension for one dispatched subtask."""
        latest = await self._socm_store.load(self._session_id)
        latest.budget.consume_query(1)
        await self._socm_store.save(self._session_id, latest)

    async def _run_subagent_ephemeral(self, subtask: dict[str, Any]) -> None:
        """Run one sub-agent on a fresh ephemeral harness (PR4 parallel, F-R28).

        PR5: the factory returns ``(harness, evidence_intake)``. The Extraction
        extension (hooked on ``tool_result``) buffers fetched pages; the engine
        sets the ContextVar before the prompt so the extension knows the
        subtask's entity, then flushes the intake at sub-agent exit (drain point,
        F-R30). The judge fills SOCM directly — the old direct-fill path is gone.
        """
        if self._subagent_factory is None:
            raise RuntimeError(
                "CoverageEngine requires a subagent_factory for parallel dispatch "
                "(F-R28); the serial main-harness fallback is unsafe under max_parallel>1."
            )
        search_tools = [t for t in self._all_tools if is_search_tool(t.name)]
        harness, intake = await self._subagent_factory.build_ephemeral(
            tools=search_tools,
            socm_store=self._socm_store,
            session_id=self._session_id,
            judge_model=self._judge_model,
            emit_event=self._emit_event,
            task_id=self._task_id,
            skills=self._search_skills,
            extraction_skills=self._extraction_skills,
        )
        try:
            agent = harness.agent
            state = await self._socm_store.load(self._session_id)
            # ContextVar: tell the Extraction extension which entity to extract for.
            current_subtask.set(subtask)
            await self._run_subagent_prompt(harness, agent, state, subtask)
            # Drain the extraction buffer (judge fills SOCM) at sub-agent exit.
            if intake is not None:
                try:
                    await intake.flush()
                except Exception:  # noqa: BLE001
                    _log.exception("extraction flush failed for subtask %s", subtask.get("question"))
            # v0.3.1 SSE: subagent_end after flush (evidence already in SOCM).
            await self._emit_event(
                "subagent_end",
                {"entity": subtask.get("entity_id", ""),
                 "cells": subtask.get("target_cells", []), "task_id": self._task_id},
            )
        finally:
            current_subtask.set(None)
            try:
                await harness.shutdown()
            except Exception:  # noqa: BLE001
                pass

    async def _run_subagent_prompt(
        self, harness: Any, agent: Any, state: SOCMState, subtask: dict[str, Any]
    ) -> None:
        base_prompt = _SEARCH_RUNTIME_PROMPT
        if self._skill_composer is not None:
            agent.state.systemPrompt = self._skill_composer.compose(base_prompt, self._search_skills, "search")
            self._journal_append(
                "skill.apply",
                {"skill_ids": [s.skill_id or s.name for s in self._search_skills], "task_id": self._task_id},
            )
        else:
            agent.state.systemPrompt = base_prompt
        prompt = _build_subagent_prompt(state, subtask)
        entity_id = subtask.get("entity_id", "")
        t0 = time.monotonic()
        try:
            await harness.prompt(prompt)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            _log.exception("sub-agent prompt failed for subtask %s", subtask.get("question"))
            self._journal_append(
                "help.requested",
                {
                    "reason": "subagent_llm_failure",
                    "entity": subtask.get("entity_id", ""),
                    "task_id": self._task_id,
                },
            )
            return
        # v0.2.2 trace: record a span for the sub-agent LLM call.
        usage = last_usage(agent.state.messages)
        await self._emit_event(
            "span",
            {
                "kind": "subagent", "stage": "search", "task_id": self._task_id,
                "entity": entity_id, "model": model_name(agent.state.model),
                "prompt_tokens": int(usage.get("input", 0) or 0),
                "completion_tokens": int(usage.get("output", 0) or 0),
                "latency_ms": int((time.monotonic() - t0) * 1000),
            },
        )

    async def _update_projection(self) -> None:
        state = await self._socm_store.load(self._session_id)
        task = await self._store.get_task(self._task_id)
        if task is None:
            return
        projection = task.get("projection") or {}
        projection["coverage"] = state.coverage_map.to_projection()
        await self._store.update_task_status(self._task_id, task["status"], projection=projection)


# ----------------------------------------------------------------- helpers


def _parse_plan_queries(plan_output: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract per-entity typed queries + source hints from the plan (Tier-2a).

    Plan schema (optional field, added in v0.2.1): ``queries`` is a list of
    ``{"entity_id": "...", "queries": ["..."], "source_hints": ["..."]}``.
    Returns a dict keyed by entity_id. Tolerant: missing/malformed → empty dict.
    """
    out: dict[str, dict[str, Any]] = {}
    raw = plan_output.get("queries")
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        eid = str(item.get("entity_id") or "").strip()
        if not eid:
            continue
        queries = item.get("queries") or []
        if not isinstance(queries, list):
            queries = []
        queries = [str(q) for q in queries if q]
        hints = item.get("source_hints") or []
        if not isinstance(hints, list):
            hints = []
        hints = [str(h) for h in hints if h]
        out[eid] = {"queries": queries, "source_hints": hints}
    return out


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


def _build_subtasks(
    cells: list[Any], max_parallel: int, chunk: int = 3
) -> list[dict[str, Any]]:
    """Batch actionable cells by entity + chunk into up to max_parallel subtasks (PR4 + Tier-2b).

    Tier-2b: each entity's cells are split into chunks of ``chunk`` cells, so a
    single entity with many cells produces multiple subtasks and the parallel pool
    can fill ``max_parallel`` even with few entities (the old one-subtask-per-entity
    design capped parallelism at the entity count — e.g. 2 entities → 2 sub-agents).
    Returns at most ``max_parallel`` subtasks, highest-leverage first; remaining
    chunks are deferred to the next iteration (the loop re-evaluates each round).
    """
    by_entity: dict[str, list[str]] = {}
    for cell in cells:
        by_entity.setdefault(cell.entity_id, []).append(f"{cell.entity_id}.{cell.attribute_id}")
    # Sort entities by cell count desc (highest leverage first).
    ranked = sorted(by_entity.items(), key=lambda kv: len(kv[1]), reverse=True)
    chunk = max(1, chunk)
    subtasks: list[dict[str, Any]] = []
    for entity_id, entity_cells in ranked:
        # Split this entity's cells into chunks; each chunk is one subtask.
        for i in range(0, len(entity_cells), chunk):
            if len(subtasks) >= max_parallel:
                return subtasks
            cell_group = entity_cells[i : i + chunk]
            subtasks.append(
                {
                    "entity_id": entity_id,
                    "target_cells": cell_group,
                    "question": f"Fill coverage cells for {entity_id}: {', '.join(cell_group)}",
                }
            )
    return subtasks


def _build_subagent_prompt(state: SOCMState, subtask: dict[str, Any]) -> str:
    cells_desc = "\n".join(f"  - {c}" for c in subtask.get("target_cells", []))
    # Tier-2a: inject the plan's suggested queries for this entity so the sub-agent
    # uses typed queries (official spec page / review / media) instead of bare queries.
    queries = subtask.get("queries") or []
    queries_block = ""
    if queries:
        qlist = "\n".join(f"  - {q}" for q in queries)
        queries_block = (
            f"\nSuggested search queries for this entity (use these first, then refine):\n{qlist}\n"
        )
    source_hints = subtask.get("source_hints") or []
    hints_block = ""
    if source_hints:
        hlist = ", ".join(source_hints)
        hints_block = f"\nAuthoritative source hints: {hlist}\n"
    return (
        f"Research intent: {state.intent}\n\n"
        f"Subtask: {subtask.get('question')}\n"
        f"Cells to fill (entity.attribute):\n{cells_desc}\n"
        f"{queries_block}{hints_block}\n"
        f"Use search tools (*_search) to find pages, then fetch them (*_fetch). "
        f"MULTI-SOURCE REQUIREMENT: for EACH target cell, fetch at least 2 independent "
        f"sources from DIFFERENT domains (e.g. official site + reputable review/media). "
        f"Do NOT stop after a single source — corroborate. Prefer official spec pages "
        f"and reputable tech media over aggregator/aggregator-wiki pages.\n\n"
        f"Return JSON: {{\"evidence\": [{{\"source\": \"<url>\", \"content\": \"<finding>\"}}]}}. "
        f"If no evidence found for a cell, return {{\"evidence\": []}} — do NOT fabricate values."
    )


_SEARCH_RUNTIME_PROMPT = "You are a search sub-agent. Find pages and fetch them to fill coverage cells."


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
