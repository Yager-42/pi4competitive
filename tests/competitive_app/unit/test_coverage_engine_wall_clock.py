"""CoverageEngine wall-clock deadline: search must self-terminate at max_wall_seconds.

Regression for A2 eval: `max_wall_seconds` was never enforced in the search loop,
so a slow-model A2 case ran to the external 900s abort. The engine now records a
deadline and (a) checks it at each iteration top and (b) bounds the parallel
sub-agent pool wait, cancelling in-flight sub-agents when it expires.
"""

from __future__ import annotations

import asyncio
import time
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

    async def save(self, _session_id: str, state: SOCMState) -> None:
        self.state = state

    async def atomic_update(self, _session_id: str, fn) -> SOCMState:
        self.state = fn(self.state)
        return self.state


class _TaskStore:
    def __init__(self) -> None:
        self.status = "running"

    async def get_task(self, _task_id: str) -> dict[str, Any]:
        return {"status": self.status}

    async def update_task_status(self, _task_id: str, status: str, projection: dict[str, Any] | None = None) -> None:
        self.status = status


class _AgentState:
    def __init__(self) -> None:
        self.systemPrompt = ""
        self.messages: list[Any] = []
        self.model: dict[str, Any] = {}


class _Agent:
    def __init__(self) -> None:
        self.state = _AgentState()


class _SlowHarness:
    """Sub-agent harness whose prompt blocks, simulating a slow model call."""

    def __init__(self, delay: float = 0.3) -> None:
        self.agent = _Agent()
        self._delay = delay

    async def prompt(self, _p: str) -> None:
        await asyncio.sleep(self._delay)

    async def shutdown(self) -> None:
        return None


class _Factory:
    def __init__(self, harness: _SlowHarness) -> None:
        self._harness = harness

    async def build_ephemeral(self, **kwargs: Any) -> tuple[_SlowHarness, None]:
        return self._harness, None


def _state_with_cells(n_attrs: int = 4) -> SOCMState:
    coverage = CoverageMap.from_schema(
        table_id="t",
        entities=[Entity(id="e", name="E", kind=EntityType.TARGET)],
        attributes=[
            Attribute(id=f"a{i}", name=f"A{i}", dimension="d", type=AttributeType.TEXT)
            for i in range(n_attrs)
        ],
    )
    return SOCMState(intent="compare E", coverage_map=coverage)


def _build_engine(store: _Store, *, max_wall: int | None, factory: _Factory | None = None) -> CoverageEngine:
    engine = object.__new__(CoverageEngine)
    engine._skill_composer = None
    engine._search_skills = []
    engine._extraction_skills = []
    engine._journal_append = lambda *_a, **_k: None
    engine._task_id = "t"

    async def _noop_emit(*_a, **_k) -> None:
        return None

    engine._emit_event = _noop_emit
    engine._socm_store = store
    engine._store = _TaskStore()
    engine._session_id = "s"
    engine._all_tools = []
    engine._max_queries = None
    engine._max_wall_seconds = max_wall
    engine._wall_deadline = None
    engine._pause_event = None
    engine._subagent_factory = factory
    engine._judge_model = None
    engine._max_iterations = 3
    engine._max_stalled = 2
    engine._max_parallel = 2
    engine._max_cell_attempts = 2
    engine._subtask_chunk = 2
    engine._coverage_threshold = 0.8
    engine._abort = asyncio.Event()
    engine._plan_queries = {}
    engine._harness = None
    return engine


@pytest.mark.asyncio
async def test_wall_clock_deadline_terminates_slow_search() -> None:
    store = _Store(_state_with_cells())
    factory = _Factory(_SlowHarness(delay=1.0))
    engine = _build_engine(store, max_wall=1, factory=factory)
    t0 = time.monotonic()

    schema = {
        "table_id": "t",
        "entities": [{"id": "e", "name": "E", "kind": "target"}],
        "attributes": [
            {"id": f"a{i}", "name": f"A{i}", "type": "text"} for i in range(4)
        ],
    }
    out = await engine.run({"coverage_schema": schema, "plan": "compare E"})

    elapsed = time.monotonic() - t0
    # max_wall=1 → must terminate well under a single slow sub-agent round (no hang).
    assert elapsed < 5.0, f"search did not self-terminate at wall-clock deadline ({elapsed:.1f}s)"
    assert "coverage" in out


@pytest.mark.asyncio
async def test_wall_remaining_zero_after_deadline() -> None:
    engine = _build_engine(_Store(_state_with_cells()), max_wall=None)
    engine._wall_deadline = time.monotonic() - 1.0
    assert engine._wall_remaining() == 0.0
    engine._wall_deadline = time.monotonic() + 5.0
    assert engine._wall_remaining() > 4.0
