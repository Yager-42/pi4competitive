"""Unit tests — Tier-0/1/2 search-quality fixes (research-workflow-v1 v0.2.1).

Covers:
- A2: junk placeholder filtering → UNKNOWN (not FILLED), and low-confidence → UNKNOWN.
- A1: multi-source judge extraction → fill() candidates has >1 entry (corroboration).
- D: subtask chunking (one entity many cells → multiple subtasks).
- C: plan queries parsing + injection into subtasks.
"""
from __future__ import annotations

import asyncio

import pytest

from competitive_app.application.workflow.coverage_engine import (
    _build_subtasks,
    _parse_plan_queries,
)
from competitive_app.application.workflow.extraction import _is_junk_value
from competitive_app.domain.socm import (
    Attribute,
    AttributeType,
    CellStatus,
    CoverageMap,
    Entity,
    EntityType,
    SOCMState,
)


# ------------------------------------------------------------- junk detection


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Not specified", True),
        ("N/A", True),
        ("n/a", True),
        ("未知", True),
        ("未公布", True),
        ("暂未公布", True),
        ("TBD", True),
        ("no information", True),
        ("—", True),
        ("4499元", False),
        ("12GB", False),
        ("5999 RMB", False),
        ("8GB RAM", False),
        ("支持", False),
    ],
)
def test_is_junk_value(value: str, expected: bool) -> None:
    assert _is_junk_value(value) is expected


# ---------------------------------------------- junk → UNKNOWN via EvidenceIntake


def _state_one_cell() -> SOCMState:
    cm = CoverageMap.from_schema(
        table_id="t",
        entities=[Entity(id="e_a", name="A", kind=EntityType.TARGET)],
        attributes=[Attribute(id="a_p", name="P", dimension="pricing", type=AttributeType.MONEY_USD)],
    )
    return SOCMState(intent="test", coverage_map=cm)


@pytest.mark.asyncio
async def test_junk_finding_routes_to_unknown_not_filled(tmp_path) -> None:
    """A judge finding with a junk value must NOT fill the cell — mark_unknown instead."""
    from competitive_app.adapter.out.persistence.socm_store import SocmStore
    from competitive_app.application.workflow.extraction import EvidenceIntake

    store = SocmStore(tmp_path)
    await store.save("sid", _state_one_cell())

    # Fake models: judge returns a junk value for the only attribute.
    class _FakeModels:
        async def completeSimple(self, model, context):
            return {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": '[{"attribute":"a_p","value":"Not specified","source":"u","source_excerpt":"","confidence":0.5}]'}
                ],
            }

    intake = EvidenceIntake(
        socm_store=store, session_id="sid", models=_FakeModels(), judge_model={"id": "j"}
    )
    intake.submit("e_a", "page text with no price", "u")
    added = await intake.flush()

    assert added == 0  # junk rejected → no evidence node
    state = await store.load("sid")
    cell = state.coverage_map.get_cell("e_a", "a_p")
    assert cell.status == CellStatus.UNKNOWN  # not FILLED with junk
    assert cell.attempts == 1


@pytest.mark.asyncio
async def test_low_confidence_finding_routes_to_unknown(tmp_path) -> None:
    """A below-min-confidence finding must not fill — mark_unknown (re-searchable)."""
    from competitive_app.adapter.out.persistence.socm_store import SocmStore
    from competitive_app.application.workflow.extraction import EvidenceIntake

    store = SocmStore(tmp_path)
    await store.save("sid", _state_one_cell())

    class _FakeModels:
        async def completeSimple(self, model, context):
            # confidence 0.2 < SEARCH_MIN_CONFIDENCE default 0.4
            return {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": '[{"attribute":"a_p","value":"$10","source":"forum","source_excerpt":"x","confidence":0.2}]'}
                ],
            }

    intake = EvidenceIntake(
        socm_store=store, session_id="sid", models=_FakeModels(), judge_model={"id": "j"}
    )
    intake.submit("e_a", "some page", "forum")
    await intake.flush()

    state = await store.load("sid")
    cell = state.coverage_map.get_cell("e_a", "a_p")
    assert cell.status == CellStatus.UNKNOWN
    assert cell.attempts == 1


@pytest.mark.asyncio
async def test_multisource_findings_corroborate_via_candidates(tmp_path) -> None:
    """Two findings for the same attr (multi-source) → fill() support path, candidates grow."""
    from competitive_app.adapter.out.persistence.socm_store import SocmStore
    from competitive_app.application.workflow.extraction import EvidenceIntake

    store = SocmStore(tmp_path)
    await store.save("sid", _state_one_cell())

    class _FakeModels:
        async def completeSimple(self, model, context):
            # Same value from two different sources — multi-source corroboration.
            return {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": '[{"attribute":"a_p","value":"$10","source":"official","source_excerpt":"x","confidence":0.9},'
                        '{"attribute":"a_p","value":"$10","source":"review","source_excerpt":"y","confidence":0.8}]',
                    }
                ],
            }

    intake = EvidenceIntake(
        socm_store=store, session_id="sid", models=_FakeModels(), judge_model={"id": "j"}
    )
    intake.submit("e_a", "page", "official")
    added = await intake.flush()

    assert added == 2  # both findings recorded as evidence nodes
    state = await store.load("sid")
    cell = state.coverage_map.get_cell("e_a", "a_p")
    assert cell.status == CellStatus.FILLED
    assert cell.confidence == 0.9  # max of the two


# ------------------------------------------------------------- subtask chunking (D)


def _cells(entity: str, n: int) -> list:
    from competitive_app.domain.socm import Cell

    return [Cell(entity_id=entity, attribute_id=f"a_{i}") for i in range(n)]


def test_subtask_chunking_splits_one_entity_into_multiple_subtasks():
    cells = _cells("e_a", 6)
    subtasks = _build_subtasks(cells, max_parallel=4, chunk=3)
    assert len(subtasks) == 2  # 6 cells / chunk 3 = 2 subtasks
    assert all(s["entity_id"] == "e_a" for s in subtasks)
    assert [len(s["target_cells"]) for s in subtasks] == [3, 3]


def test_subtask_chunking_respects_max_parallel():
    cells = _cells("e_a", 12)  # would be 4 subtasks at chunk=3
    subtasks = _build_subtasks(cells, max_parallel=2, chunk=3)
    assert len(subtasks) == 2  # capped at max_parallel


def test_subtask_chunking_two_entities():
    cells = _cells("e_a", 3) + _cells("e_b", 3)
    subtasks = _build_subtasks(cells, max_parallel=4, chunk=3)
    # e_a has 3 cells (1 subtask), e_b has 3 cells (1 subtask) → 2 subtasks
    assert len(subtasks) == 2
    entities = {s["entity_id"] for s in subtasks}
    assert entities == {"e_a", "e_b"}


# ------------------------------------------------------- plan queries parsing (C)


def test_parse_plan_queries_extracts_per_entity():
    plan = {
        "plan": "markdown",
        "queries": [
            {"entity_id": "e_a", "queries": ["q1", "q2"], "source_hints": ["gsmarena.com"]},
            {"entity_id": "e_b", "queries": ["q3"], "source_hints": []},
        ],
    }
    out = _parse_plan_queries(plan)
    assert out["e_a"]["queries"] == ["q1", "q2"]
    assert out["e_a"]["source_hints"] == ["gsmarena.com"]
    assert out["e_b"]["queries"] == ["q3"]


def test_parse_plan_queries_tolerant_missing():
    assert _parse_plan_queries({"plan": "x"}) == {}
    assert _parse_plan_queries({"queries": "not a list"}) == {}
    assert _parse_plan_queries({"queries": [{"queries": ["q"]}]}) == {}  # no entity_id
