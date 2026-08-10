"""CaseManifest schema + loader tests (D5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from eval.manifest import CaseManifest, load_manifest
from pydantic import ValidationError


def _sample_case(case_id: str = "ws_en_001") -> dict:
    return {
        "case_id": case_id,
        "benchmark": "widesearch",
        "benchmark_revision": "abc123",
        "language": "en",
        "category": "business",
        "source_task_id": case_id,
        "query": "Compare Apple iPhone 15 vs Samsung Galaxy S24 specs.",
        "research_brief": {
            "target": {"name": "iPhone 15 vs Galaxy S24", "category": "benchmark"},
            "goal": "Compare Apple iPhone 15 vs Samsung Galaxy S24 specs.",
            "competitors": ["Apple iPhone 15", "Samsung Galaxy S24"],
            "dimensions": ["price", "screen", "chipset"],
        },
        "license": "MIT",
        "notes": "",
    }


def test_case_manifest_parses_valid():
    m = CaseManifest.model_validate(_sample_case())
    assert m.case_id == "ws_en_001"
    assert m.benchmark == "widesearch"
    assert m.research_brief.competitors == ["Apple iPhone 15", "Samsung Galaxy S24"]
    assert m.research_brief.dimensions == ["price", "screen", "chipset"]


def test_case_manifest_requires_competitors_min_1():
    raw = _sample_case()
    raw["research_brief"]["competitors"] = []
    with pytest.raises(ValidationError):
        CaseManifest.model_validate(raw)


def test_case_manifest_rejects_unknown_benchmark():
    raw = _sample_case()
    raw["benchmark"] = "unknown_bench"
    with pytest.raises(ValidationError):
        CaseManifest.model_validate(raw)


def test_load_manifest_reads_jsonl(tmp_path: Path):
    p = tmp_path / "manifest.jsonl"
    content = (
        json.dumps(_sample_case("ws_en_001")) + "\n" + json.dumps(_sample_case("ws_en_002")) + "\n"
    )
    p.write_text(content, encoding="utf-8")
    cases = load_manifest(p)
    assert len(cases) == 2
    assert cases[0].case_id == "ws_en_001"
    assert cases[1].case_id == "ws_en_002"
