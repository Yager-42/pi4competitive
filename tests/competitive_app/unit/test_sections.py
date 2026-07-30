"""Unit tests — _split_sections (v0.2.2 write section derivation)."""
from __future__ import annotations

from competitive_app.application.workflow.research_runner import _split_sections


def test_split_sections_basic():
    md = "# 报告标题\n\n## 一、定价\n内容A\n\n## 二、规格\n内容B"
    s = _split_sections(md)
    assert [x["id"] for x in s] == ["1", "2"]
    assert s[0]["title"] == "一、定价"
    assert s[1]["title"] == "二、规格"
    assert "内容A" in s[0]["body"]
    assert "## 一、定价" in s[0]["body"]  # body includes heading
    assert "内容B" in s[1]["body"]


def test_split_sections_top_level_h1_skipped():
    """Top-level `#` (report title) is NOT a section; content before first ## dropped."""
    md = "# Title\nintro text\n\n## Section 1\nbody"
    s = _split_sections(md)
    assert len(s) == 1
    assert s[0]["title"] == "Section 1"
    assert "intro text" not in s[0]["body"]  # intro dropped


def test_split_sections_sources_kept():
    """## Sources is kept as a refinable section."""
    md = "# T\n\n## A\nb\n\n## Sources\n[1] x"
    s = _split_sections(md)
    assert [x["title"] for x in s] == ["A", "Sources"]


def test_split_sections_empty():
    assert _split_sections("") == []
    assert _split_sections("# only title") == []


def test_split_sections_no_h2():
    """No `##` → no sections (all content is title/intro, dropped)."""
    assert _split_sections("# Title\n\nplain paragraph") == []
