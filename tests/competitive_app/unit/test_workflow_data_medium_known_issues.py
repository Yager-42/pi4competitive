from __future__ import annotations

import asyncio
import fcntl

import pytest

from competitive_app.adapter.out.persistence.socm_store import SocmStore
from competitive_app.application.workflow.coverage_engine import CoverageEngine
from competitive_app.application.workflow.extraction import EvidenceIntake
from competitive_app.domain.socm import (
    Attribute,
    AttributeType,
    CoverageMap,
    Entity,
    EntityType,
    SOCMState,
)
from competitive_app.domain.socm.strategy import Budget


def _state() -> SOCMState:
    coverage = CoverageMap.from_schema(
        table_id="t",
        entities=[Entity(id="e", name="E", kind=EntityType.TARGET)],
        attributes=[Attribute(id="a", name="A", dimension="d", type=AttributeType.TEXT)],
    )
    return SOCMState(coverage_map=coverage)


@pytest.mark.asyncio
async def test_socm_flock_wait_does_not_block_event_loop(tmp_path) -> None:
    store = SocmStore(tmp_path)
    await store.save("s", SOCMState())
    lock_fd = open(tmp_path / "s" / ".search_state.json.lock", "r")
    ticked = False
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        async def tick() -> None:
            nonlocal ticked
            await asyncio.sleep(0.02)
            ticked = True

        delete_task = asyncio.create_task(store.delete("s"))
        await asyncio.gather(tick(), asyncio.sleep(0.05))
        assert ticked and not delete_task.done()
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
    await delete_task


def test_stronger_same_value_refreshes_provenance() -> None:
    state = _state()
    state.coverage_map.fill("e", "a", value="v", source="weak", source_excerpt="old", confidence=0.5)
    cell = state.coverage_map.fill(
        "e", "a", value="v", source="strong", source_excerpt="new", confidence=0.9
    )
    assert cell.confidence == 0.9
    assert cell.source == "strong"
    assert cell.source_excerpt == "new"


def test_wall_budget_rejects_finite_sum_overflow() -> None:
    budget = Budget(consumed_wall_seconds=1e308)
    with pytest.raises(ValueError, match="finite range"):
        budget.consume_wall(1e308)


@pytest.mark.asyncio
async def test_repeated_source_observations_validate_any_excerpt() -> None:
    state = _state()

    class Store:
        async def load(self, _session: str) -> SOCMState:
            return state

        async def atomic_update(self, _session: str, updater):
            updater(state)
            return state

    class Models:
        async def completeSimple(self, _model, _context):
            return {
                "content": [{"type": "text", "text": (
                    '[{"attribute":"a","value":"ok","source":"u",'
                    '"source_excerpt":"earlier", "confidence":0.9}]'
                )}]
            }

    intake = EvidenceIntake(
        socm_store=Store(), session_id="s", models=Models(), judge_model={"id": "j"}
    )
    intake.submit("e", "earlier", "u")
    intake.submit("e", "later", "u")
    assert await intake.flush() == 1
    assert state.coverage_map.get_cell("e", "a").source == "u"


@pytest.mark.asyncio
async def test_query_allowance_is_atomic() -> None:
    class Store:
        def __init__(self):
            self.state = _state()
            self.state.budget.max_queries = 1
            self.lock = asyncio.Lock()

        async def atomic_update(self, _session, updater):
            async with self.lock:
                return updater(self.state)

    store = Store()
    engine = object.__new__(CoverageEngine)
    engine._socm_store = store
    engine._session_id = "s"
    results = await asyncio.gather(engine._consume_query_budget(), engine._consume_query_budget())
    assert sorted(results) == [False, True]
    assert store.state.budget.consumed_queries == 1
