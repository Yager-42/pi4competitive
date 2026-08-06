"""Unit — _clamp_search_overrides: clamp + drop type errors (v0.3.5)."""
from __future__ import annotations

from competitive_app.application.workflow.task_service import _clamp_search_overrides


def test_clamp_high() -> None:
    out = _clamp_search_overrides({"max_parallel": 100, "coverage_threshold": 5.0})
    assert out == {"max_parallel": 16, "coverage_threshold": 1.0}


def test_clamp_low() -> None:
    out = _clamp_search_overrides({"max_parallel": 0, "coverage_threshold": 0.0, "max_queries": -1})
    assert out == {"max_parallel": 1, "coverage_threshold": 0.05, "max_queries": 1}


def test_valid_passthrough() -> None:
    out = _clamp_search_overrides(
        {"max_parallel": 8, "coverage_threshold": 0.3, "max_queries": 10, "max_wall_seconds": 120}
    )
    assert out == {"max_parallel": 8, "coverage_threshold": 0.3, "max_queries": 10, "max_wall_seconds": 120}


def test_drop_type_errors() -> None:
    out = _clamp_search_overrides(
        {"max_parallel": "abc", "coverage_threshold": None, "max_queries": [1], "max_wall_seconds": "60"}
    )
    # string "60" coerces to int 60 (valid); "abc"/list dropped; None dropped
    assert out == {"max_wall_seconds": 60}


def test_empty_and_non_dict() -> None:
    assert _clamp_search_overrides({}) == {}
    assert _clamp_search_overrides(None) == {}  # type: ignore[arg-type]
    assert _clamp_search_overrides("not a dict") == {}  # type: ignore[arg-type]


def test_string_number_coerces() -> None:
    out = _clamp_search_overrides({"max_parallel": "4", "coverage_threshold": "0.5"})
    assert out == {"max_parallel": 4, "coverage_threshold": 0.5}
