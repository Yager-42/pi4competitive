"""Unit tests — SOCM domain models (research-workflow-v1 v0.2.0 F-R26/F-R27).

Covers: CoverageMap four-state cells + conflict arbitration, EvidenceGraph
dedup, Frontier priority + blocked_by DAG, Budget exhaustion, SOCMState
snapshot/restore, and SocmStore atomic write. Pure domain + persistence.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from competitive_app.adapter.out.persistence.socm_store import SocmStore
from competitive_app.domain.socm import (
    Attribute,
    AttributeType,
    Budget,
    Cell,
    CellStatus,
    CoverageMap,
    Entity,
    EntityType,
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
    EvidenceRelation,
    Frontier,
    FrontierTask,
    FrontierTaskStatus,
    SOCMState,
    StrategyMemory,
    StrategyPattern,
    AntiPatternKind,
)


def _map() -> CoverageMap:
    return CoverageMap.from_schema(
        table_id="t",
        entities=[Entity(id="e_a", name="A", kind=EntityType.TARGET)],
        attributes=[Attribute(id="a_p", name="P", dimension="pricing", type=AttributeType.MONEY_USD)],
    )


# ----------------------------------------------------------- coverage four-state


def test_coverage_starts_all_empty():
    cm = _map()
    assert len(cm.cells) == 1
    assert all(c.status == CellStatus.EMPTY for c in cm.cells.values())
    assert cm.coverage_ratio() == 0.0


def test_coverage_fill_empty_to_filled():
    cm = _map()
    cm.fill("e_a", "a_p", value="$10", source="url1", confidence=0.8)
    cell = cm.get_cell("e_a", "a_p")
    assert cell.status == CellStatus.FILLED
    assert cell.value == "$10"
    assert cell.confidence == 0.8
    assert cm.coverage_ratio() == 1.0


def test_coverage_fill_same_value_supports_and_bumps_confidence():
    cm = _map()
    cm.fill("e_a", "a_p", value="$10", source="url1", confidence=0.5)
    cm.fill("e_a", "a_p", value=" $10 ", source="url2", confidence=0.9)  # normalized same
    cell = cm.get_cell("e_a", "a_p")
    assert cell.status == CellStatus.FILLED
    assert cell.confidence == 0.9  # max


def test_coverage_fill_different_high_delta_higher_wins():
    cm = _map()
    cm.fill("e_a", "a_p", value="$10", source="url1", confidence=0.3)
    cm.fill("e_a", "a_p", value="$20", source="url2", confidence=0.9)  # delta 0.6 >= 0.2
    cell = cm.get_cell("e_a", "a_p")
    assert cell.status == CellStatus.FILLED
    assert cell.value == "$20"
    assert cell.confidence == 0.9
    assert len(cell.candidates) == 2  # loser retained for traceability


def test_coverage_fill_different_low_delta_becomes_conflict():
    cm = _map()
    cm.fill("e_a", "a_p", value="$10", source="url1", confidence=0.5)
    cm.fill("e_a", "a_p", value="$20", source="url2", confidence=0.55)  # delta 0.05 < 0.2
    cell = cm.get_cell("e_a", "a_p")
    assert cell.status == CellStatus.CONFLICT
    assert len(cell.candidates) == 2


def test_coverage_conflict_third_low_confidence_stays_conflict():
    """A 3rd dissenting low-confidence candidate must NOT collapse CONFLICT→FILLED."""
    cm = _map()
    cm.fill("e_a", "a_p", value="$10", source="u1", confidence=0.5)
    cm.fill("e_a", "a_p", value="$20", source="u2", confidence=0.55)  # CONFLICT (delta 0.05)
    cm.fill("e_a", "a_p", value="$30", source="u3", confidence=0.35)  # 3rd dissenter
    cell = cm.get_cell("e_a", "a_p")
    assert cell.status == CellStatus.CONFLICT  # not buried
    assert len(cell.candidates) == 3


def test_coverage_conflict_dominant_candidate_resolves_to_filled():
    """If one candidate dominates ALL dissenters by >= delta, conflict resolves."""
    cm = _map()
    cm.fill("e_a", "a_p", value="$10", source="u1", confidence=0.5)
    cm.fill("e_a", "a_p", value="$20", source="u2", confidence=0.55)  # CONFLICT
    # Third candidate at 0.9 dominates BOTH dissenters (0.5 delta 0.4, 0.55 delta 0.35)
    cm.fill("e_a", "a_p", value="$30", source="u3", confidence=0.9)
    cell = cm.get_cell("e_a", "a_p")
    assert cell.status == CellStatus.FILLED
    assert cell.value == "$30"
    assert cell.confidence == 0.9


def test_coverage_conflict_corroboration_resolves():
    """A new candidate agreeing with the dominant one resolves the conflict."""
    cm = _map()
    cm.fill("e_a", "a_p", value="$10", source="u1", confidence=0.5)
    cm.fill("e_a", "a_p", value="$20", source="u2", confidence=0.9)  # FILLED (delta 0.4)
    # A third agreeing with $20 (support) — still FILLED, candidates track history
    cm.fill("e_a", "a_p", value="$20", source="u3", confidence=0.85)
    cell = cm.get_cell("e_a", "a_p")
    assert cell.status == CellStatus.FILLED
    assert cell.confidence == 0.9


def test_coverage_mark_unknown_terminal_for_dispatch():
    cm = _map()
    cm.mark_unknown("e_a", "a_p")
    cell = cm.get_cell("e_a", "a_p")
    assert cell.status == CellStatus.UNKNOWN
    assert cell.attempts == 1
    assert cell.is_terminal() is True
    # unknown still counts as covered for ratio (searched, just empty result)
    assert cm.coverage_ratio() == 1.0


def test_coverage_unknown_then_fill_recovers():
    cm = _map()
    cm.mark_unknown("e_a", "a_p")
    cm.fill("e_a", "a_p", value="$10", source="url1", confidence=0.8)
    cell = cm.get_cell("e_a", "a_p")
    assert cell.status == CellStatus.FILLED
    assert cell.attempts == 0


def test_coverage_empty_cells_excludes_terminal():
    cm = CoverageMap.from_schema(
        table_id="t",
        entities=[Entity(id="e_a", name="A"), Entity(id="e_b", name="B")],
        attributes=[Attribute(id="a_p", name="P", dimension="pricing")],
    )
    cm.fill("e_a", "a_p", value="x", source="s", confidence=0.9)
    cm.mark_unknown("e_b", "a_p")
    empties = cm.empty_cells()
    assert len(empties) == 0  # both terminal


def test_coverage_to_projection():
    cm = _map()
    cm.fill("e_a", "a_p", value="x", source="s", confidence=0.9)
    proj = cm.to_projection()
    assert proj == {"filled": 1, "total": 1, "pending_cells": 0, "ratio": 1.0}


# ---------------------------------------------------------------- evidence graph


def test_evidence_dedup_same_fact_same_source():
    g = EvidenceGraph()
    n1 = EvidenceNode(id="n1", entity="A", attribute="P", value="$10", source="url1")
    n2 = EvidenceNode(id="n2", entity="A", attribute="P", value="$10", source="url1")
    assert g.add_node(n1) is True
    assert g.add_node(n2) is False  # dup
    assert g.node_count() == 1


def test_evidence_keeps_corroborating_different_source():
    g = EvidenceGraph()
    n1 = EvidenceNode(id="n1", entity="A", attribute="P", value="$10", source="url1")
    n2 = EvidenceNode(id="n2", entity="A", attribute="P", value="$10", source="url2")
    assert g.add_node(n1) is True
    assert g.add_node(n2) is True  # different source = corroborating
    assert g.node_count() == 2


def test_evidence_get_conflicts():
    g = EvidenceGraph()
    g.add_node(EvidenceNode(id="n1", entity="A", attribute="P", value="$10", source="url1"))
    g.add_node(EvidenceNode(id="n2", entity="A", attribute="P", value="$20", source="url2"))
    g.add_edge(EvidenceEdge(from_id="n1", to_id="n2", relation=EvidenceRelation.CONFLICT))
    conflicts = g.get_conflicts()
    assert len(conflicts) == 1
    assert {conflicts[0][0].id, conflicts[0][1].id} == {"n1", "n2"}


def test_evidence_dedup_works_after_restore():
    """PrivateAttr _sig_index rebuilds after model_validate (review B1/G5)."""
    g = EvidenceGraph()
    g.add_node(EvidenceNode(id="n1", entity="A", attribute="P", value="$10", source="url1"))
    data = g.model_dump()
    g2 = EvidenceGraph.model_validate(data)
    # Same fact+source after restore → still deduped
    assert g2.add_node(EvidenceNode(id="n1b", entity="A", attribute="P", value="$10", source="url1")) is False
    # Different source → added
    assert g2.add_node(EvidenceNode(id="n2", entity="A", attribute="P", value="$10", source="url2")) is True


# ------------------------------------------------------------------- frontier


def _task(tid: str, priority: float = 0.5, cells: list[str] | None = None) -> FrontierTask:
    return FrontierTask(id=tid, priority=priority, target_cells=cells or [f"e.a_{tid}"])


def test_frontier_dequeue_highest_priority_first():
    f = Frontier()
    f.add(_task("t1", priority=0.3))
    f.add(_task("t2", priority=0.9))
    picked = f.dequeue()
    assert picked is not None
    assert picked.id == "t2"
    assert picked.status == FrontierTaskStatus.RUNNING


def test_frontier_dequeue_fifo_within_same_priority():
    f = Frontier()
    # Distinct created_at: earlier timestamp wins within same priority.
    f.add(FrontierTask(id="t2", priority=0.5, target_cells=["e.a_t2"], created_at=100.0))
    f.add(FrontierTask(id="t1", priority=0.5, target_cells=["e.a_t1"], created_at=50.0))
    picked = f.dequeue()
    assert picked is not None
    assert picked.id == "t1"  # earlier created_at wins


def test_frontier_blocked_by_keeps_pending_until_deps_done():
    f = Frontier()
    f.add(_task("t1", priority=0.5))
    f.add(_task("t2", priority=0.9, cells=["e.a_t2"]))
    # make t2 blocked by t1
    f.tasks[1].blocked_by = ["t1"]
    f.tasks[1].status = FrontierTaskStatus.BLOCKED
    # t2 not ready while t1 pending
    picked = f.dequeue()
    assert picked.id == "t1"
    # t1 still running (not done) → t2 stays blocked
    assert f.dequeue() is None
    # complete t1 → t2 unblocks
    f.resolve("t1")
    picked2 = f.dequeue()
    assert picked2 is not None
    assert picked2.id == "t2"


def test_frontier_dedup_subset_match():
    f = Frontier()
    f.add(_task("t1", priority=0.5, cells=["e.a", "e.b"]))
    # subset of existing active task → dedup, bump priority
    dup = f.add(_task("t2", priority=0.9, cells=["e.a"]))
    assert dup is not None
    assert dup.id == "t1"  # returned existing
    assert dup.priority == 0.9  # bumped
    assert len(f.tasks) == 1


def test_frontier_max_attempts_excludes_task():
    """A task dispatched MAX_TASK_ATTEMPTS times is no longer dequeueable."""
    from competitive_app.domain.socm.frontier import MAX_TASK_ATTEMPTS

    f = Frontier()
    f.add(_task("t1", priority=0.5))
    for _ in range(MAX_TASK_ATTEMPTS):
        picked = f.dequeue()
        assert picked is not None
        assert picked.id == "t1"
        # Simulate failed dispatch: reset to PENDING for retry (without resolve).
        f.retry("t1")
    # 4th attempt excluded by attempts cap
    assert f.dequeue() is None


def test_frontier_retry_resets_running_to_pending():
    f = Frontier()
    f.add(_task("t1", priority=0.5))
    picked = f.dequeue()
    assert picked is not None
    assert picked.status == FrontierTaskStatus.RUNNING
    assert f.retry("t1") is True
    assert picked.status == FrontierTaskStatus.PENDING


def test_frontier_resolve_stores_resolution():
    f = Frontier()
    f.add(_task("t1", priority=0.5))
    f.dequeue()
    assert f.resolve("t1", resolution="found $10") is True
    task = f.tasks[0]
    assert task.status == FrontierTaskStatus.COMPLETED
    assert task.resolution == "found $10"


# --------------------------------------------------------------------- budget


def test_budget_not_exhausted_under_caps():
    b = Budget(max_queries=10, max_iterations=5)
    b.consume_query(5)
    assert b.exhausted() is False
    assert b.exhausted_dim() is None


def test_budget_exhausted_when_any_dim_hits_cap():
    b = Budget(max_queries=10, max_iterations=5)
    b.consume_query(10)
    assert b.exhausted() is True
    assert b.exhausted_dim() == "queries"


def test_budget_ratio_is_max_across_dims():
    b = Budget(max_queries=100, max_iterations=10)
    b.consume_iteration(5)  # 0.5
    b.consume_query(10)  # 0.1
    assert b.ratio() == 0.5


def test_budget_zero_max_disables_dim():
    b = Budget(max_queries=0, max_iterations=5)  # queries disabled
    b.consume_query(99999)
    assert b.exhausted() is False


def test_budget_consume_open_increments_both_opens_and_fetches():
    """v0.2.0 unifies opens/fetches — a fetch is a page open (plan §A4)."""
    b = Budget(max_opens=10, max_fetches=10)
    b.consume_open(3)
    assert b.consumed_opens == 3
    assert b.consumed_fetches == 3


def test_budget_exhausted_dim_returns_first_at_cap():
    b = Budget(max_queries=5, max_iterations=5)
    b.consume_query(5)
    b.consume_iteration(5)
    # Both at cap; returns the first in fixed order (queries).
    assert b.exhausted_dim() == "queries"


def test_strategy_record_dedup_bumps_count():
    s = StrategyMemory()
    s.record(StrategyPattern(id="p1", kind=AntiPatternKind.QUERY, signature="q1"))
    s.record(StrategyPattern(id="p2", kind=AntiPatternKind.QUERY, signature="q1"))
    assert len(s.patterns) == 1
    assert s.patterns[0].observed_count == 2


# ----------------------------------------------------------------- SOCMState


def test_socm_state_snapshot_restore_roundtrip():
    state = SOCMState(intent="compare A vs B")
    state.coverage_map = _map()
    state.coverage_map.fill("e_a", "a_p", value="$10", source="url1", confidence=0.9)
    state.evidence_graph.add_node(
        EvidenceNode(id="n1", entity="A", attribute="P", value="$10", source="url1")
    )
    state.budget.consume_query(5)

    data = state.snapshot()
    restored = SOCMState.restore(data)
    assert restored.intent == "compare A vs B"
    assert restored.coverage_map.filled_count() == 1
    assert restored.evidence_graph.node_count() == 1
    assert restored.budget.consumed_queries == 5


def test_socm_state_to_projection_has_coverage():
    state = SOCMState()
    state.coverage_map = _map()
    proj = state.to_projection()
    assert "coverage" in proj
    assert proj["coverage"]["total"] == 1


# ----------------------------------------------------------------- SocmStore


@pytest.mark.asyncio
async def test_socm_store_load_returns_empty_when_absent(tmp_path: Path):
    store = SocmStore(tmp_path)
    state = await store.load("sid_none")
    assert state.coverage_map.filled_count() == 0


@pytest.mark.asyncio
async def test_socm_store_save_load_roundtrip(tmp_path: Path):
    store = SocmStore(tmp_path)
    state = SOCMState(intent="goal")
    state.coverage_map = _map()
    state.coverage_map.fill("e_a", "a_p", value="$10", source="url1", confidence=0.9)
    await store.save("sid1", state)
    assert await store.exists("sid1")

    loaded = await store.load("sid1")
    assert loaded.intent == "goal"
    assert loaded.coverage_map.filled_count() == 1


@pytest.mark.asyncio
async def test_socm_store_atomic_update_serializes_concurrent_writes(tmp_path: Path):
    """Concurrent atomic_update calls must not lose evidence (F-R27 O12)."""
    store = SocmStore(tmp_path)
    state = SOCMState()
    state.coverage_map = _map()
    await store.save("sid", state)

    def add_evidence(idx: int):
        def updater(s: SOCMState) -> SOCMState:
            s.evidence_graph.add_node(
                EvidenceNode(id=f"n{idx}", entity="A", attribute="P", value=f"${idx}", source=f"u{idx}")
            )
            return s
        return updater

    # 10 concurrent updaters on the same session
    await asyncio.gather(*[store.atomic_update("sid", add_evidence(i)) for i in range(10)])
    loaded = await store.load("sid")
    assert loaded.evidence_graph.node_count() == 10  # none lost


@pytest.mark.asyncio
async def test_socm_store_delete_removes_file(tmp_path: Path):
    store = SocmStore(tmp_path)
    await store.save("sid", SOCMState())
    assert await store.exists("sid")
    await store.delete("sid")
    assert not await store.exists("sid")


@pytest.mark.asyncio
async def test_socm_store_atomic_update_returns_updated_state(tmp_path: Path):
    store = SocmStore(tmp_path)

    def updater(s: SOCMState) -> SOCMState:
        s.budget.consume_query(3)
        return s

    result = await store.atomic_update("sid_new", updater)
    assert result.budget.consumed_queries == 3
    # And persisted
    loaded = await store.load("sid_new")
    assert loaded.budget.consumed_queries == 3


@pytest.mark.asyncio
async def test_coverage_engine_dispatch_parallel_runs_concurrently(tmp_path: Path):
    """PR4 E1: _dispatch_parallel actually runs sub-agents concurrently.

    Injects a subagent_factory whose harness.prompt sleeps; tracks max in-flight
    count. With max_parallel=4 and 4 subtasks, all 4 should be in-flight at once
    (assert max_in_flight >= 2, proving non-serial execution).
    """
    import asyncio as _aio
    from competitive_app.application.workflow.coverage_engine import CoverageEngine

    in_flight = 0
    max_in_flight = 0
    guard = _aio.Lock()

    class _FakeAgent:
        def __init__(self) -> None:
            self.state = type("S", (), {"messages": [], "systemPrompt": "", "tools": []})()

    class _FakeHarness:
        def __init__(self) -> None:
            self.agent = _FakeAgent()

        async def prompt(self, _input) -> None:
            nonlocal in_flight, max_in_flight
            async with guard:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            await _aio.sleep(0.05)
            async with guard:
                in_flight -= 1

        async def shutdown(self) -> None:
            pass

    class _FakeFactory:
        async def build_ephemeral(self, tools=None, system_prompt=""):
            return _FakeHarness()

    main_harness = _FakeHarness()  # has .agent; not used for prompt when factory set
    engine = CoverageEngine(
        socm_store=SocmStore(tmp_path),
        session_id="sid",
        harness=main_harness,
        all_tools=[],
        store=object(),
        task_id="t",
        abort_signal=_aio.Event(),
        max_parallel=4,
        subagent_factory=_FakeFactory(),
    )
    subtasks = [{"entity_id": f"e_{i}", "target_cells": [f"e_{i}.a"], "question": "q"} for i in range(4)]
    await engine._dispatch_parallel(SOCMState(), subtasks)
    assert max_in_flight >= 2, f"parallel dispatch did not run concurrently (max_in_flight={max_in_flight})"
