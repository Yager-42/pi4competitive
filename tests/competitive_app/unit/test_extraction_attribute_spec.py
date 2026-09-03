"""The judge prompt must state each column's value shape (P2).

The plan stage declares a type per attribute, and for enums the exact members,
but the judge was handed only attribute ids. So it wrote prose into typed
columns and six sources phrased one billing unit six ways ("per member /
month", "per seat per month", "per user/month") — which the coverage map could
only record as six-way disagreement. On the measured run 27 of the 47 remaining
conflicts were enum columns whose declared members never appeared in any value.
"""
from __future__ import annotations

from competitive_app.application.workflow.extraction import (
    _attribute_spec,
    _build_judge_prompt,
)
from competitive_app.domain.socm.coverage import Attribute, AttributeType


def _attr(attr_id: str, attr_type: AttributeType, **kwargs: object) -> Attribute:
    return Attribute.model_validate(
        {"id": attr_id, "name": kwargs.pop("name", ""), "dimension": "d",
         "type": attr_type, **kwargs}
    )


def test_enum_spec_lists_the_declared_members_verbatim() -> None:
    spec = _attribute_spec(
        _attr("a_billing_unit", AttributeType.ENUM,
              enum_values=["per_user_month", "flat_month", "none"])
    )
    assert "per_user_month" in spec
    assert "flat_month" in spec
    assert "EXACTLY ONE" in spec


def test_bool_spec_asks_for_a_leading_polarity() -> None:
    spec = _attribute_spec(_attr("a_offline_access", AttributeType.BOOL))
    assert "Yes" in spec and "No" in spec


def test_money_spec_asks_for_period() -> None:
    spec = _attribute_spec(_attr("a_paid_start_price", AttributeType.MONEY_USD))
    assert "billing period" in spec


def test_text_spec_has_no_fixed_list() -> None:
    spec = _attribute_spec(_attr("a_platforms", AttributeType.TEXT))
    assert "EXACTLY ONE" not in spec
    assert "a_platforms" in spec


def test_spec_includes_human_name_when_present() -> None:
    spec = _attribute_spec(_attr("a_free_tier", AttributeType.BOOL, name="Free tier"))
    assert "a_free_tier" in spec and "Free tier" in spec


def test_bare_id_string_still_renders() -> None:
    """`_call_judge` accepts plain ids (older callers and tests)."""
    assert _attribute_spec("a_legacy") == "- a_legacy"


def test_prompt_carries_specs_and_keeps_prose_in_the_excerpt() -> None:
    prompt = _build_judge_prompt(
        "e_notion",
        [
            _attr("a_billing_unit", AttributeType.ENUM,
                  enum_values=["per_user_month", "flat_month"]),
            _attr("a_offline_access", AttributeType.BOOL),
        ],
        "[0] https://example.com\nsome page text",
    )
    assert "per_user_month" in prompt
    assert "a_offline_access" in prompt
    # The instruction that keeps paraphrase out of the value.
    assert "do NOT paraphrase" in prompt
    assert "source_excerpt, which is where prose belongs" in prompt
    # Existing contract still intact.
    assert "Output ONLY the JSON array" in prompt
    assert "e_notion" in prompt


def test_prompt_accepts_bare_ids_without_schema() -> None:
    prompt = _build_judge_prompt("e_x", ["a_one", "a_two"], "pages")
    assert "- a_one" in prompt and "- a_two" in prompt
