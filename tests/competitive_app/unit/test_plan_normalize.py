"""Plan-output guardrail: aggregate-row → per-item expansion (v0.2.11).

The plan LLM sometimes ignores ENTITY GRANULARITY and emits the whole topic +
category as entities (aggregate rows), so brief-enumerated concrete items (12
countries for a policy table) are never searchable per-row. ``normalize_plan_output``
deterministically expands them into per-item entities scoped to policy attributes.
"""
from __future__ import annotations

from competitive_app.application.workflow.plan_normalize import (
    _extract_enumerated_items,
    normalize_plan_output,
)


def _schema(attributes: list[dict], entities: list[dict] | None = None) -> dict:
    return {
        "table_id": "t_competitive",
        "entities": entities
        or [
            {"id": "e_topic", "name": "Life Cycle Cost of Electric Vehicles", "kind": "target"},
            {"id": "e_ev", "name": "Electric Vehicles", "kind": "competitor"},
        ],
        "attributes": attributes,
        "queries": [
            {"entity_id": "e_topic", "queries": ["EV LCC study"], "source_hints": []},
        ],
    }


def _policy_attrs() -> list[dict]:
    return [
        {"id": "a_lcc", "name": "LCC (USD)", "type": "money_usd"},
        {"id": "a_research_source", "name": "Research Source", "type": "text"},
        {"id": "a_policy_country", "name": "Country", "type": "text"},
        {"id": "a_policy_name", "name": "Policy/Regulation Name", "type": "text"},
        {"id": "a_policy_year", "name": "Policy Year", "type": "number"},
        {"id": "a_policy_brief", "name": "Policy Brief", "type": "text"},
    ]


_GOAL = (
    "Please cover at least Canada, the United States, Spain, the Netherlands, "
    "Italy, Switzerland, Turkey, Denmark, France, Germany, Portugal, and Belgium."
)


def test_expands_enumerated_countries_scoped_to_policy_attrs():
    plan = {"plan": "x", "coverage_schema": _schema(_policy_attrs())}
    out = normalize_plan_output(plan, _GOAL)

    schema = out["coverage_schema"]
    names = [e["name"] for e in schema["entities"]]
    # 12 countries + 2 originals
    assert len(names) == 14
    for country in ("Canada", "United States", "Netherlands", "Portugal", "Belgium"):
        assert country in names
    # originals kept (as cost subjects)
    assert "Life Cycle Cost of Electric Vehicles" in names

    scope = schema["entity_attributes"]
    country_ids = {
        e["id"] for e in schema["entities"] if e["name"] == "Canada"
    }
    canada = country_ids.pop()
    assert set(scope[canada]) == {
        "a_policy_country", "a_policy_name", "a_policy_year", "a_policy_brief"
    }
    # original aggregate rows scoped to NON-policy attrs only
    assert set(scope["e_topic"]) == {"a_lcc", "a_research_source"}
    assert all("policy" not in aid for aid in scope["e_topic"])
    # every item entity scoped to policy ids
    for e in schema["entities"]:
        if e["name"] not in ("Life Cycle Cost of Electric Vehicles", "Electric Vehicles"):
            assert set(scope[e["id"]]) == {
                "a_policy_country", "a_policy_name", "a_policy_year", "a_policy_brief"
            }, e

    # queries: original 1 + 12 new
    assert len(schema["queries"]) == 13
    assert any("Canada" in q["queries"][0] for q in schema["queries"])


def test_extract_items_drb2_22_style():
    items = _extract_enumerated_items(_GOAL)
    assert items == [
        "Canada", "United States", "Spain", "Netherlands", "Italy",
        "Switzerland", "Turkey", "Denmark", "France", "Germany", "Portugal",
        "Belgium",
    ]


def test_extract_items_ignores_column_specs_and_sections():
    """A full DRB-II-style brief mixes column specs, section lists and a country
    list. Only the country enumeration must be extracted — table headers and
    section titles are attributes/structure, not row entities."""
    goal = (
        "I need you to organize this data into a table, with columns including: "
        "'Vehicle Model/Study Code', 'Research Source (format: First Author, "
        "Year)', and 'LCC (USD)'. Please present this in a table format, with "
        "columns including: 'Country', 'Policy/Regulation Name', 'Year', and "
        "'Policy Brief'. Please cover at least Canada, the United States, Spain, "
        "the Netherlands, Italy, Switzerland, Turkey, Denmark, France, Germany, "
        "Portugal, and Belgium."
    )
    items = _extract_enumerated_items(goal)
    assert items == [
        "Canada", "United States", "Spain", "Netherlands", "Italy",
        "Switzerland", "Turkey", "Denmark", "France", "Germany", "Portugal",
        "Belgium",
    ]


def test_extract_items_ignores_following_sections():
    goal = (
        "Please complete the following sections:\n"
        "1. **Cost Data Compilation for Different Vehicle Models**: collect costs.\n"
        "2. **Summary of Incentive Policies by Country**: list policies.\n"
        "Please cover at least Canada and Spain."
    )
    items = _extract_enumerated_items(goal)
    assert "Cost Data Compilation for Different Vehicle Models" not in items
    assert items == ["Canada", "Spain"]


def test_extract_items_ignores_blocked_reference_json():
    """The DRB II blocked-reference block ("the following article and urls:
    {'title': ...}") must never leak title fragments or author names as items."""
    goal = (
        "During the research process, you are not allowed to view the following "
        "article and urls: {'title': 'Life Cycle Cost Assessment of Electric "
        "Vehicles: A Review and Bibliometric Analysis', 'authors': ['Bamidele "
        "Victor Ayodele', 'Siti Indati Mustapa'], 'urls': ['https://www.mdpi.com/"
        "2071-1050/12/6/2387']}. Please cover at least Canada, Spain, and Belgium."
    )
    items = _extract_enumerated_items(goal)
    assert "A Review" not in items
    assert "Bamidele Victor Ayodele" not in items
    assert items == ["Canada", "Spain", "Belgium"]


def test_noop_without_enumerated_items():
    plan = {"plan": "x", "coverage_schema": _schema(_policy_attrs())}
    out = normalize_plan_output(plan, "Just write a report about EV life cycle cost.")
    assert out is plan  # identical object — untouched


def test_noop_without_policy_attrs():
    attrs = [{"id": "a_lcc", "name": "LCC (USD)", "type": "money_usd"}]
    out = normalize_plan_output({"plan": "x", "coverage_schema": _schema(attrs)}, _GOAL)
    assert out["coverage_schema"]["entities"] is not None
    assert len(out["coverage_schema"]["entities"]) == 2  # unchanged


def test_missing_items_are_added_existing_not_duplicated():
    entities = [
        {"id": "e_topic", "name": "EV LCC", "kind": "target"},
        {"id": "e_canada", "name": "Canada", "kind": "competitor"},
        {"id": "e_us", "name": "United States", "kind": "competitor"},
    ]
    plan = {"plan": "x", "coverage_schema": _schema(_policy_attrs(), entities)}
    out = normalize_plan_output(plan, _GOAL)
    names = [e["name"] for e in out["coverage_schema"]["entities"]]
    assert len(names) == 13  # 3 existing + 10 missing countries
    assert names.count("Canada") == 1  # no duplicate for an existing item
    assert names.count("United States") == 1
    assert "Spain" in names  # missing ones still added


def test_noop_on_malformed_plan():
    assert normalize_plan_output(None, _GOAL) is None
    assert normalize_plan_output({"plan": "x"}, _GOAL) == {"plan": "x"}
    assert normalize_plan_output({"plan": "x", "coverage_schema": "nope"}, _GOAL) == {
        "plan": "x", "coverage_schema": "nope"
    }


def test_single_item_is_not_expanded():
    # "such as" with one item is an example, not an enumeration → don't expand.
    plan = {"plan": "x", "coverage_schema": _schema(_policy_attrs())}
    out = normalize_plan_output(plan, "Research policies such as Canada.")
    assert len(out["coverage_schema"]["entities"]) == 2
