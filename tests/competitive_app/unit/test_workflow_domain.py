"""Unit tests — STAGES / StageResult schema / ResearchBrief (research-workflow-v1 v0.2.0).

Three stages (plan/search/write); v0.1.1 six-stage tests rewritten.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from competitive_app.domain.research_brief import ResearchBrief, TargetIdentity
from competitive_app.domain.stage import (
    STAGES,
    STAGE_DEPENDENCIES,
    STAGE_OUTPUT_SCHEMA,
    empty_projection,
    validate_stage_output,
)


def test_stages_three_in_order() -> None:
    assert STAGES == ("plan", "search", "write")


def test_stage_output_schema_covers_all_stages() -> None:
    for name in STAGES:
        assert name in STAGE_OUTPUT_SCHEMA


def test_stage_dependencies_chain() -> None:
    assert STAGE_DEPENDENCIES["plan"] == ()
    assert STAGE_DEPENDENCIES["search"] == ("plan",)
    assert STAGE_DEPENDENCIES["write"] == ("search",)


def test_empty_projection_three_stages_and_coverage() -> None:
    proj = empty_projection()
    assert proj["current_stage"] is None
    for name in STAGES:
        assert proj["stages"][name] == "pending"
    assert "coverage" in proj
    assert proj["coverage"] == {"filled": 0, "total": 0, "pending_cells": 0}


def test_validate_stage_output_ok() -> None:
    result = validate_stage_output("plan", {"plan": "search ACME"})
    assert result.ok is True
    assert result.error is None


def test_validate_stage_output_missing_field() -> None:
    result = validate_stage_output("search", {"wrong": "x"})
    assert result.ok is False
    assert "coverage" in (result.error or "")


def test_validate_stage_output_empty_field() -> None:
    result = validate_stage_output("write", {"report": ""})
    assert result.ok is False
    assert "report" in (result.error or "")


def test_research_brief_minimal() -> None:
    brief = ResearchBrief(
        target=TargetIdentity(name="ACME"),
        goal="analyze ACME",
        competitors=["ACME"],
        dimensions=["pricing"],
    )
    assert brief.competitors == ["ACME"]


def test_research_brief_requires_competitors() -> None:
    with pytest.raises(ValidationError):
        ResearchBrief(
            target=TargetIdentity(name="ACME"),
            goal="g",
            competitors=[],
            dimensions=["pricing"],
        )


def test_research_brief_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        ResearchBrief.model_validate(
            {
                "target": {"name": "ACME"},
                "goal": "g",
                "competitors": ["A"],
                "dimensions": ["pricing"],
                "breadth": "core_direct",  # legacy field, rejected (F-R6)
            }
        )
