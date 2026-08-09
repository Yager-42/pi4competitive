"""research-workflow v0.2.9 (A1) — sub-agent multi-turn round-2 supplement.

``_run_subagent_prompt`` now runs TWO ``harness.prompt`` calls when round 1
leaves target cells EMPTY: round 1 searches all cells; the intake is flushed
into SOCM; round 2 supplements the cells still empty. A second user message is
what lets reasonix fold round 1 and produce a compaction entry (previously the
session was single-turn → ``activeTurnEntryIds=ALL`` → fold=∅).
"""
from __future__ import annotations

from typing import Any

import pytest
from competitive_app.application.workflow.coverage_engine import CoverageEngine
from competitive_app.domain.socm import (
    Attribute,
    AttributeType,
    CoverageMap,
    Entity,
    EntityType,
    SOCMState,
)


class _Store:
    def __init__(self, state: SOCMState) -> None:
        self.state = state

    async def load(self, _session_id: str) -> SOCMState:
        return self.state


class _AgentState:
    def __init__(self) -> None:
        self.systemPrompt = ""
        self.messages: list[Any] = []
        self.model: dict[str, Any] = {}


class _Agent:
    def __init__(self) -> None:
        self.state = _AgentState()


class _Harness:
    def __init__(self) -> None:
        self.agent = _Agent()
        self.prompts: list[str] = []

    async def prompt(self, p: str) -> None:
        self.prompts.append(p)

    async def shutdown(self) -> None:
        return None


class _Intake:
    """Fake intake whose flush fills specific cells (simulates round-1 judge)."""

    def __init__(self, store: _Store, fill_on_flush: list[tuple[str, str]]) -> None:
        self._store = store
        self._fill = fill_on_flush
        self.flushed = 0

    async def flush(self) -> int:
        self.flushed += 1
        for entity, attr in self._fill:
            self._store.state.coverage_map.fill(
                entity, attr, value="v", source="u", source_excerpt="x", confidence=0.9,
            )
        return len(self._fill)


def _two_cells() -> SOCMState:
    coverage = CoverageMap.from_schema(
        table_id="t",
        entities=[Entity(id="e", name="E", kind=EntityType.TARGET)],
        attributes=[
            Attribute(id="a1", name="A1", dimension="d", type=AttributeType.TEXT),
            Attribute(id="a2", name="A2", dimension="d", type=AttributeType.TEXT),
        ],
    )
    return SOCMState(intent="compare E", coverage_map=coverage)


def _build_engine(store: _Store) -> CoverageEngine:
    async def _noop_emit(*_a, **_k) -> None:
        return None

    engine = object.__new__(CoverageEngine)
    engine._skill_composer = None
    engine._search_skills = []
    engine._journal_append = lambda *_a, **_k: None
    engine._task_id = "t"
    engine._emit_event = _noop_emit
    engine._socm_store = store
    engine._session_id = "s"
    return engine


@pytest.mark.asyncio
async def test_round2_supplements_cells_round1_left_empty() -> None:
    store = _Store(_two_cells())
    engine = _build_engine(store)
    harness = _Harness()
    # Round 1 fills e.a1 (via intake flush); e.a2 stays EMPTY → round 2 targets it.
    intake = _Intake(store, fill_on_flush=[("e", "a1")])
    subtask = {"entity_id": "e", "target_cells": ["e.a1", "e.a2"], "question": "fill"}

    await engine._run_subagent_prompt(
        harness, harness.agent, store.state, subtask, intake=intake,
    )

    assert len(harness.prompts) == 2
    assert intake.flushed == 1
    # Round 2 prompt names the still-empty cell.
    assert "e.a2" in harness.prompts[1]
    assert "e.a1" not in harness.prompts[1].split("Cells to fill")[1]


@pytest.mark.asyncio
async def test_round2_skipped_when_all_target_cells_filled() -> None:
    store = _Store(_two_cells())
    engine = _build_engine(store)
    harness = _Harness()
    # Round 1 fills BOTH target cells → no empty cells → round 2 skipped.
    intake = _Intake(store, fill_on_flush=[("e", "a1"), ("e", "a2")])
    subtask = {"entity_id": "e", "target_cells": ["e.a1", "e.a2"], "question": "fill"}

    await engine._run_subagent_prompt(
        harness, harness.agent, store.state, subtask, intake=intake,
    )

    assert len(harness.prompts) == 1
    assert intake.flushed == 1


@pytest.mark.asyncio
async def test_no_intake_means_single_turn() -> None:
    store = _Store(_two_cells())
    engine = _build_engine(store)
    harness = _Harness()
    subtask = {"entity_id": "e", "target_cells": ["e.a1", "e.a2"], "question": "fill"}

    await engine._run_subagent_prompt(
        harness, harness.agent, store.state, subtask, intake=None,
    )

    assert len(harness.prompts) == 1


@pytest.mark.asyncio
async def test_round1_failure_skips_round2_and_flush() -> None:
    store = _Store(_two_cells())
    engine = _build_engine(store)
    intake = _Intake(store, fill_on_flush=[("e", "a1")])
    subtask = {"entity_id": "e", "target_cells": ["e.a1", "e.a2"], "question": "fill"}

    class _FailHarness(_Harness):
        async def prompt(self, p: str) -> None:
            self.prompts.append(p)
            raise RuntimeError("llm down")

    fail_harness = _FailHarness()
    await engine._run_subagent_prompt(
        fail_harness, fail_harness.agent, store.state, subtask, intake=intake,
    )

    assert len(fail_harness.prompts) == 1  # round 1 attempted
    assert intake.flushed == 0  # flush only runs after a successful round 1
