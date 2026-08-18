"""DRB II adapter: dataset row -> CaseManifest (D1 C2-wide)."""

from __future__ import annotations

from eval.adapter.drb2 import build_case_manifest, parse_drb2_row


def _row() -> dict:
    return {
        "id": "task10",
        "idx": 22,
        "language": "en",
        "theme": "Science & Technology",
        "description": "The Life Cycle Cost of Electric Vehicles and Policy Support",
        "prompt": "I would like you to help me research the Life Cycle Cost (LCC) of "
        "Electric Vehicles (EVs). My research report needs to cover data up to 2019.",
        "license": "CC BY 4.0",
    }


def test_parse_drb2_row_extracts_public_fields_only():
    parsed = parse_drb2_row(_row())
    assert parsed["idx"] == 22
    assert parsed["id"] == "task10"
    assert parsed["language"] == "en"
    assert parsed["license"] == "CC BY 4.0"
    assert "rubric" not in parsed  # 打分侧内容绝不进 manifest


def test_build_case_manifest_from_prompt():
    m = build_case_manifest(_row(), benchmark_revision="rev@abc")
    assert m.case_id == "drb2_22"
    assert m.benchmark == "drb2"
    assert m.source_task_id == "drb2_22"
    assert m.language == "en"
    assert "Life Cycle Cost" in m.query
    assert m.research_brief.goal == _row()["prompt"]
    assert len(m.research_brief.competitors) >= 1
    assert m.research_brief.dimensions == ["overview"]
    assert m.license == "CC BY 4.0"
    assert m.benchmark_revision == "rev@abc"


def test_build_case_manifest_falls_back_to_description():
    row = _row()
    row["prompt"] = "Please write a report covering the above scope."
    m = build_case_manifest(row, benchmark_revision="r")
    assert m.research_brief.competitors  # 非空 (退回 description)
