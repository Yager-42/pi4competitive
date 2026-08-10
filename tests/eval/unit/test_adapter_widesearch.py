"""WideSearch input adapter: official task -> CaseManifest (D5 §5.2)."""

from __future__ import annotations

import json

from eval.adapter.widesearch import build_case_manifest, parse_widesearch_row


def _ws_row(
    instance_id="ws_en_001",
    query="Compare Apple iPhone 15 vs Samsung Galaxy S24 specs. Output a Markdown table with columns: price, screen, chipset.",
):
    return {
        "instance_id": instance_id,
        "query": query,
        "evaluation": json.dumps(
            {
                "unique_columns": ["price"],
                "required": ["price", "screen", "chipset"],
                "eval_pipeline": {},
            }
        ),
        "language": "en",
    }


def test_parse_row_extracts_query_and_required():
    row = _ws_row()
    parsed = parse_widesearch_row(row)
    assert parsed["instance_id"] == "ws_en_001"
    assert "Apple iPhone 15" in parsed["query"]
    assert parsed["required"] == ["price", "screen", "chipset"]
    assert parsed["language"] == "en"


def test_build_manifest_competitors_from_query():
    row = _ws_row()
    m = build_case_manifest(row, benchmark_revision="abc123")
    assert m.case_id == "ws_en_001"
    assert m.benchmark == "widesearch"
    # competitors must come from query text, not gold
    assert (
        "Apple iPhone 15" in m.research_brief.competitors[0]
        or "Samsung Galaxy S24" in m.research_brief.competitors[0]
    )
    assert m.research_brief.dimensions == ["price", "screen", "chipset"]
    assert m.research_brief.goal.startswith("Compare Apple iPhone 15")


def test_build_manifest_rejects_no_competitor_query():
    row = _ws_row(
        query="List the top 5 universities by QS ranking. Output a Markdown table with columns: name, rank."
    )
    # query has no明确实体 -> competitors 无法构造 -> raise (S4 规则)
    import pytest

    with pytest.raises(ValueError, match="competitors"):
        build_case_manifest(row, benchmark_revision="abc123")
