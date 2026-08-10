"""WideSearch normalizer: report.md -> WideSearchResponse JSONL (D10 N1)."""
from __future__ import annotations

import json
from pathlib import Path

from eval.normalizer.widesearch import extract_markdown_table, normalize_report


def test_extract_table_finds_required_headers():
    md = """# Report

Some intro text.

| subject | university | rank |
|---------|------------|-----|
| CS | MIT | 1 |
| Physics | Harvard | 2 |

More text.
"""
    table = extract_markdown_table(md, required=["subject", "university", "rank"])
    assert "| subject | university | rank |" in table
    assert "MIT" in table


def test_extract_table_returns_none_if_missing_headers():
    md = "| a | b |\n|---|---|\n| 1 | 2 |"
    assert extract_markdown_table(md, required=["subject", "university"]) is None


def test_normalize_report_writes_jsonl(tmp_path: Path):
    md = "| subject | university |\n|---|---|\n| CS | MIT |"
    out = tmp_path / "competitorlens_a2_ws_en_001_0_response.jsonl"
    normalize_report(
        report_md=md,
        required_headers=["subject", "university"],
        instance_id="ws_en_001",
        model_config_name="competitorlens_a2",
        trial_idx=0,
        out_path=out,
    )
    line = out.read_text(encoding="utf-8").strip()
    obj = json.loads(line)
    assert obj["instance_id"] == "ws_en_001"
    assert "| subject | university |" in obj["response"]
    assert obj["trial_idx"] == 0


def test_normalize_report_no_table_writes_empty_response(tmp_path: Path):
    out = tmp_path / "x.jsonl"
    normalize_report(
        report_md="no table here",
        required_headers=["subject"],
        instance_id="ws_en_002",
        model_config_name="competitorlens_a2",
        trial_idx=0,
        out_path=out,
    )
    obj = json.loads(out.read_text(encoding="utf-8").strip())
    assert obj["response"] == ""  # F5: empty response, scorer scores 0
    assert obj["instance_id"] == "ws_en_002"
