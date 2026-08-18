"""Write-stage section selection: plan report_structure overrides generic outline.

v0.2.10: DRB II 报告轨按任务 prompt 明确指定的结构判分（精确表格/章节名）；
写阶段按 plan ``report_structure`` → brief 程序化提取 → 通用 overview/dims/conclusion
的优先级组织章节。
"""

from __future__ import annotations

from competitive_app.application.workflow.research_runner import (
    _COST_TABLE_STUDY_RULE,
    ResearchRunner,
    _extract_report_structure_from_brief,
    _is_cost_table_title,
)
from competitive_app.domain.research_brief import ResearchBrief


def _runner() -> ResearchRunner:
    r = object.__new__(ResearchRunner)
    r.research_brief = ResearchBrief(
        target={"name": "EV LCC", "category": "benchmark"},
        goal="Research the life cycle cost of EVs.",
        competitors=["Electric Vehicles"],
        dimensions=["overview"],
    )
    return r


def test_section_list_uses_report_structure():
    runner = _runner()
    plan = {
        "report_structure": [
            {
                "section": "Cost Data Compilation for Different Vehicle Models",
                "focus": "table with EV 100/200/300 columns",
            },
            {"section": "Summary of Incentive Policies by Country", "focus": "policy table"},
        ]
    }
    sections = runner._section_list(plan)  # type: ignore[attr-defined]
    assert len(sections) == 2
    assert sections[0] == (
        "struct:0",
        "Cost Data Compilation for Different Vehicle Models",
        "table with EV 100/200/300 columns",
    )
    assert sections[1][1] == "Summary of Incentive Policies by Country"


def test_section_list_falls_back_to_generic_without_structure():
    runner = _runner()
    sections = runner._section_list({})  # type: ignore[attr-defined]
    assert sections[0][0] == "overview"
    assert sections[-1][0] == "conclusion"
    # report_structure 为 None / 非 list 也退回通用
    assert runner._section_list(None)[0][0] == "overview"  # type: ignore[attr-defined]
    assert runner._section_list({"report_structure": "nope"})[0][0] == "overview"  # type: ignore[attr-defined]


def test_section_list_skips_malformed_structure_entries():
    runner = _runner()
    plan = {"report_structure": ["not-a-dict", {"section": "ok", "focus": "f"}]}
    sections = runner._section_list(plan)  # type: ignore[attr-defined]
    assert len(sections) == 1
    assert sections[0] == ("struct:1", "ok", "f")


def test_extract_report_structure_from_brief_numbered_bold():
    goal = (
        "Research EV LCC.\n"
        "1. **Cost Data Compilation for Different Vehicle Models**: collect cost columns.\n"
        "2. **Summary of Incentive Policies by Country**: policy table.\n"
        "3. **Comprehensive Analysis**: synthesize."
    )
    out = _extract_report_structure_from_brief(goal)
    assert out is not None and len(out) == 3
    assert out[0][1] == "Cost Data Compilation for Different Vehicle Models"
    assert out[0][2] == "collect cost columns."
    assert out[2][1] == "Comprehensive Analysis"


def test_extract_report_structure_no_match_returns_none():
    assert _extract_report_structure_from_brief("Just write a report about EVs.") is None


def test_section_list_falls_back_to_brief_structure():
    runner = _runner()
    runner.research_brief = ResearchBrief(
        target={"name": "EV LCC", "category": "benchmark"},
        goal=(
            "Research EV LCC.\n"
            "1. **Cost Data Compilation for Different Vehicle Models**: table.\n"
            "2. **Summary of Incentive Policies by Country**: table."
        ),
        competitors=["Electric Vehicles"],
        dimensions=["overview"],
    )
    sections = runner._section_list({"plan": "no report_structure here"})  # type: ignore[attr-defined]
    assert sections[0][1] == "Cost Data Compilation for Different Vehicle Models"
    assert sections[-1][1] == "Summary of Incentive Policies by Country"


# ------------------------------------------------- cost-table write rule (v0.2.12)


def test_is_cost_table_title():
    assert _is_cost_table_title("Cost Data Compilation for Different Vehicle Models") is True
    assert _is_cost_table_title("Life Cycle Cost Comparison by Vehicle") is True
    assert _is_cost_table_title("Comprehensive Analysis") is False
    assert _is_cost_table_title("Summary of Incentive Policies by Country") is False
    assert _is_cost_table_title("概述") is False


def test_cost_section_prompt_includes_study_rule():
    runner = _runner()
    prompt = runner._build_section_prompt(  # type: ignore[attr-defined]
        "Cost Data Compilation for Different Vehicle Models",
        "cost table",
        {"plan": {"coverage_schema": {"entities": []}}},
        None,
    )
    assert _COST_TABLE_STUDY_RULE in prompt
    # non-cost sections must NOT carry the study rule
    prompt2 = runner._build_section_prompt(  # type: ignore[attr-defined]
        "Comprehensive Analysis",
        "synthesis",
        {"plan": {}},
        None,
    )
    assert _COST_TABLE_STUDY_RULE not in prompt2
