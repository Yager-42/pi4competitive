"""Unit — _regex_brands + _coerce_competitors must_include (v0.2.8)."""
from __future__ import annotations

from competitive_app.application.workflow.task_service import (
    _build_fixed_scope_brief,
    _coerce_competitors,
    _infer_specified_entities,
    _regex_brands,
)


def test_chinese_listing() -> None:
    assert _regex_brands("飞书 与 钉钉 和 企业微信") == ["飞书", "钉钉", "企业微信"]


def test_dunhao_listing() -> None:
    # 顿号 + 尾巴描述:飞书/钉钉切准;企业微信后接中文描述无分隔(正则固有限制,但前两个必中)
    out = _regex_brands("为飞书、钉钉、企业微信做一份结构化 SWOT 竞争分析")
    assert "飞书" in out and "钉钉" in out


def test_vs_pattern() -> None:
    out = _regex_brands("Notion vs Obsidian 定价对比")
    assert "Notion" in out and "Obsidian" in out


def test_stopwords_filtered() -> None:
    out = _regex_brands("分析 对比 竞争 格局")
    assert out == []


def test_digit_dropped() -> None:
    out = _regex_brands("2024 2025 对比")
    assert out == []


def test_cap_six() -> None:
    # 2-char product-like tokens; single chars (A/B) filtered (len<2)
    out = _regex_brands("小米、华为、苹果、三星、OPPO、vivo、联想、荣耀")
    assert len(out) == 6


def test_empty() -> None:
    assert _regex_brands("") == []
    # separated stopwords filtered; unseparated "分析市场" is a known limitation
    # (no separator to split on) — acceptable as regex is fallback, LLM ignores it.
    assert _regex_brands("分析 对比 竞争 格局") == []


def test_infer_fixed_chinese_comparison_from_discovery_candidates() -> None:
    query = "分析特斯拉、比亚迪、理想在新能源车市场的产品力与定价竞争格局"
    assert _infer_specified_entities(
        query,
        "新能源汽车",
        ["特斯拉", "比亚迪", "理想", "蔚来"],
    ) == ["特斯拉", "比亚迪", "理想"]


def test_infer_fixed_entities_does_not_turn_open_competitor_query_into_closed_scope() -> None:
    assert _infer_specified_entities("特斯拉的竞品分析", "特斯拉", ["比亚迪", "理想"]) == []


def test_fixed_scope_brief_ignores_extra_entities_returned_by_llm() -> None:
    fixed = ["特斯拉", "比亚迪", "理想"]
    brief = _build_fixed_scope_brief(
        {
            "target": {"name": "蔚来", "category": "新能源汽车"},
            "goal": "比较新能源车品牌",
            "competitors": ["蔚来", *fixed],
            "dimensions": ["产品力", "定价策略"],
        },
        entities=fixed,
        domain="新能源汽车",
        query="分析特斯拉、比亚迪、理想",
    )
    assert [brief.target.name, *brief.competitors] == fixed


def test_coerce_must_include_prepended() -> None:
    # LLM returned [Slack, Teams] but query listed 飞书/钉钉 → must_include prepended
    out = _coerce_competitors(["Slack", "Teams"], ["Slack", "Teams"], must_include=["飞书", "钉钉"])
    assert out[:2] == ["飞书", "钉钉"]
    assert "Slack" in out and "Teams" in out
    assert len(out) <= 6


def test_coerce_must_include_when_llm_empty() -> None:
    # LLM returned nothing → must_include + discovered fallback
    out = _coerce_competitors(None, ["Slack", "Teams"], must_include=["飞书"])
    assert out[0] == "飞书"
    assert "Slack" in out


def test_coerce_dedup() -> None:
    out = _coerce_competitors(["飞书", "Slack"], ["飞书"], must_include=["飞书"])
    assert out.count("飞书") == 1
