"""Focused regressions for domain known issues 173-182."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from competitive_app.domain.stage import validate_stage_output
from competitive_app.domain.task import Task, TaskStatusError
from competitive_app.domain.socm.coverage import (
    Attribute,
    CoverageMap,
    Entity,
    CellStatus,
)
from competitive_app.domain.socm.evidence import EvidenceGraph, EvidenceNode
from competitive_app.domain.socm.frontier import (
    Frontier,
    FrontierTask,
    FrontierTaskStatus,
    MAX_TASK_ATTEMPTS,
)
from competitive_app.domain.socm.strategy import Budget


def _coverage() -> CoverageMap:
    return CoverageMap.from_schema(
        table_id="t",
        entities=[Entity(id="e", name="Entity")],
        attributes=[Attribute(id="a", name="Attribute", dimension="d")],
    )


def _frontier_task(task_id: str, cells: list[str], **kwargs: object) -> FrontierTask:
    return FrontierTask(id=task_id, target_cells=cells, **kwargs)


def test_conflict_resolution_preserves_candidates_for_later_dissent() -> None:
    coverage = _coverage()
    coverage.fill("e", "a", value="one", source="s1", confidence=0.5)
    coverage.fill("e", "a", value="two", source="s2", confidence=0.55)
    coverage.fill("e", "a", value="three", source="s3", confidence=0.9)
    cell = coverage.fill("e", "a", value="four", source="s4", confidence=0.8)

    assert cell.status == CellStatus.CONFLICT
    assert [candidate.value for candidate in cell.candidates] == [
        "one", "two", "three", "four"
    ]


def test_weak_filled_cell_is_actionable_without_unknown_attempt() -> None:
    coverage = _coverage()
    cell = coverage.fill("e", "a", value="weak", source="s", confidence=0.5)

    assert cell.attempts == 1
    assert coverage.actionable_cells(max_attempts=2) == [cell]
    coverage.fill("e", "a", value="weak", source="s2", confidence=0.5)
    assert cell.attempts == 2
    assert coverage.actionable_cells(max_attempts=2) == []
    assert coverage.satisfied_ratio(max_attempts=2) == 1.0


def test_evidence_claim_lookup_is_case_insensitive() -> None:
    graph = EvidenceGraph()
    node = EvidenceNode(id="n", entity="NoTiOn", attribute="PrIcE", value="$10")
    graph.add_node(node)

    assert graph.get_claims_for("notion", "price") == [node]


def test_source_less_evidence_nodes_are_not_collapsed() -> None:
    graph = EvidenceGraph()
    n1 = EvidenceNode(id="n1", entity="A", attribute="P", value="$10")
    n2 = EvidenceNode(id="n2", entity="A", attribute="P", value="$10")

    assert graph.add_node(n1) is True
    assert graph.add_node(n2) is True
    assert graph.node_count() == 2


def test_retry_at_attempt_cap_cancels_task() -> None:
    frontier = Frontier()
    frontier.add(_frontier_task("t", ["e.a"]))

    for _ in range(MAX_TASK_ATTEMPTS):
        assert frontier.dequeue() is not None
        assert frontier.retry("t") is True

    task = frontier.tasks[0]
    assert task.status == FrontierTaskStatus.CANCELLED
    assert frontier.dequeue() is None


def test_frontier_deduplicates_when_existing_task_is_subset() -> None:
    frontier = Frontier()
    frontier.add(_frontier_task("narrow", ["e.a"]))

    duplicate = frontier.add(_frontier_task("broad", ["e.a", "e.b"], priority=0.9))

    assert duplicate is not None
    assert duplicate.id == "narrow"
    assert len(frontier.tasks) == 1
    assert duplicate.priority == 0.9


def test_frontier_eviction_keeps_pending_prerequisite(monkeypatch: pytest.MonkeyPatch) -> None:
    import competitive_app.domain.socm.frontier as frontier_module

    monkeypatch.setattr(frontier_module, "MAX_FRONTIER_CAP", 2)
    frontier = Frontier()
    frontier.add(_frontier_task("dependency", ["e.dep"], priority=0.0))
    frontier.add(
        _frontier_task(
            "dependent", ["e.child"], priority=1.0, blocked_by=["dependency"]
        )
    )
    frontier.add(_frontier_task("evictable", ["e.other"], priority=0.0))

    assert {task.id for task in frontier.tasks} == {"dependency", "dependent"}
    assert frontier.dequeue() is not None
    assert frontier.tasks[1].status == FrontierTaskStatus.BLOCKED


def test_missing_frontier_dependency_never_becomes_ready() -> None:
    blocked = _frontier_task(
        "dependent", ["e.child"], blocked_by=["missing"], status=FrontierTaskStatus.BLOCKED
    )
    frontier = Frontier(tasks=[blocked])

    assert frontier.dequeue() is None
    assert blocked.status == FrontierTaskStatus.BLOCKED


@pytest.mark.parametrize(
    "field",
    ["max_queries", "max_opens", "max_fetches", "max_iterations", "max_wall_seconds"],
)
def test_budget_rejects_negative_limits(field: str) -> None:
    with pytest.raises(ValidationError):
        Budget(**{field: -1})


def test_budget_rejects_negative_counters_and_consumption() -> None:
    with pytest.raises(ValidationError):
        Budget(consumed_queries=-1)
    budget = Budget()
    for method, amount in [
        (budget.consume_query, -1),
        (budget.consume_open, -1),
        (budget.consume_iteration, -1),
        (budget.consume_wall, -1.0),
    ]:
        with pytest.raises(ValueError):
            method(amount)
    assert budget.consumed_queries == 0
    assert budget.consumed_opens == 0
    assert budget.consumed_iterations == 0
    assert budget.consumed_wall_seconds == 0.0


def test_unknown_stage_is_rejected() -> None:
    result = validate_stage_output("typo", {})

    assert result.ok is False
    assert result.error == "unknown stage: typo"


def test_task_constructor_rejects_unknown_status() -> None:
    with pytest.raises(TaskStatusError):
        Task(task_id="t", query="q", status="typo")  # type: ignore[arg-type]
