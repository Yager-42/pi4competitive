"""Unit — _assemble_report: per-section write assembly (research-workflow v0.2.6)."""

from __future__ import annotations

from competitive_app.application.workflow.research_runner import _assemble_report


def test_assemble_order_ids_and_bodies() -> None:
    sr = [
        {"title": "概述", "body": "ov", "sources": [{"n": 1, "url": "u1", "label": "l1"}]},
        {
            "title": "定价策略",
            "body": "pricing body",
            "sources": [{"n": 1, "url": "u2", "label": "l2"}],
        },
        {"title": "结论与建议", "body": "concl", "sources": []},
    ]
    report, sections = _assemble_report(sr)
    # report has each section + Sources
    assert "## 概述\nov" in report
    assert "## 定价策略\npricing body" in report
    assert "## 结论与建议\nconcl" in report
    assert "## Sources" in report
    # Sources grouped by section (### title headers)
    assert "### 概述" in report and "### 定价策略" in report
    assert "[1] u1" in report and "[1] u2" in report  # local [n], no global renumber
    # sections: sequential ids "1".."N+1", Sources last, body starts with ## title
    assert [s["id"] for s in sections] == ["1", "2", "3", "4"]
    assert sections[-1]["title"] == "Sources"
    for s in sections[:-1]:
        assert s["body"].startswith("## ")


def test_assemble_empty_sources_placeholder() -> None:
    sr = [{"title": "概述", "body": "ov", "sources": []}]
    report, sections = _assemble_report(sr)
    assert "(无来源)" in report  # no sources → placeholder in Sources block
    assert sections[-1]["title"] == "Sources"


def test_assemble_failure_section_passthrough() -> None:
    # a failed section's body ("(本节生成失败)") is assembled as-is (best-effort)
    sr = [{"title": "概述", "body": "(本节生成失败)", "sources": []}]
    report, _ = _assemble_report(sr)
    assert "(本节生成失败)" in report


def test_assemble_sources_grouped_no_global_renumber() -> None:
    # two sections each with local [1] → Sources lists [1] per section group (no collision)
    sr = [
        {"title": "A", "body": "a [1]", "sources": [{"n": 1, "url": "ua", "label": "la"}]},
        {"title": "B", "body": "b [1]", "sources": [{"n": 1, "url": "ub", "label": "lb"}]},
    ]
    report, _ = _assemble_report(sr)
    assert "### A\n[1] ua" in report
    assert "### B\n[1] ub" in report  # both [1], grouped by section — no global renumber


def test_assemble_missing_fields_tolerant() -> None:
    # missing title/sources → defaults (title=Section N, sources=(无来源))
    sr = [{"body": "just body"}, {"title": "X", "body": "xb", "sources": "not-a-list"}]
    report, sections = _assemble_report(sr)
    assert "Section 1" in report  # default title
    assert "## X\nxb" in report
    assert len(sections) == 3  # 2 + Sources
