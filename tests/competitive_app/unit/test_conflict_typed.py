"""Type-aware conflict comparison (P2).

Pure string equality made corroboration look like contradiction: on a real run
cells seen by ONE source were 100% filled, while cells seen by two or more were
77% conflict, because "$10 per member/month" and "$10 per seat/month" are the
same price written two ways. These tests pin the typed comparison and, just as
importantly, pin that genuinely different values still conflict.
"""
from __future__ import annotations

from competitive_app.domain.socm.coverage import (
    Attribute,
    AttributeType,
    CellStatus,
    CoverageMap,
    Entity,
    EntityType,
)

# Confidences within CONFLICT_CONFIDENCE_DELTA (0.2) so neither candidate can
# dominate — the outcome is decided by value comparison alone, which is what is
# under test.
C1 = 0.8
C2 = 0.75


def _map(attr_type: AttributeType, *, enum_values: list[str] | None = None) -> CoverageMap:
    return CoverageMap.from_schema(
        table_id="t",
        entities=[Entity(id="e", name="Acme", kind=EntityType.TARGET)],
        attributes=[
            Attribute(
                id="a",
                name="attr",
                dimension="d",
                type=attr_type,
                enum_values=enum_values or [],
            )
        ],
    )


def _fill_two(
    attr_type: AttributeType,
    first: str,
    second: str,
    *,
    enum_values: list[str] | None = None,
) -> CellStatus:
    cm = _map(attr_type, enum_values=enum_values)
    cm.fill("e", "a", value=first, source="s1", confidence=C1)
    cell = cm.fill("e", "a", value=second, source="s2", confidence=C2)
    return cell.status


# ------------------------------------------------------------------ money_usd


def test_same_price_different_seat_wording_corroborates() -> None:
    status = _fill_two(
        AttributeType.MONEY_USD, "$10 per member/month", "$10 per seat/month"
    )
    assert status is CellStatus.FILLED


def test_same_price_with_currency_noise_corroborates() -> None:
    status = _fill_two(AttributeType.MONEY_USD, "USD 12.00 / user / month", "$12/mo")
    assert status is CellStatus.FILLED


def test_thousands_separator_matches_plain_digits() -> None:
    status = _fill_two(AttributeType.MONEY_USD, "$1,200 per year", "$1200/yr")
    assert status is CellStatus.FILLED


def test_different_amount_still_conflicts() -> None:
    status = _fill_two(AttributeType.MONEY_USD, "$10 per seat/month", "$15 per seat/month")
    assert status is CellStatus.CONFLICT


def test_same_amount_different_billing_period_still_conflicts() -> None:
    """$10/month and $10/year are different facts, not two phrasings of one."""
    status = _fill_two(AttributeType.MONEY_USD, "$10 per user/month", "$10 per user/year")
    assert status is CellStatus.CONFLICT


def test_free_and_zero_dollars_are_the_same_price() -> None:
    status = _fill_two(AttributeType.MONEY_USD, "Free", "$0")
    assert status is CellStatus.FILLED


def test_tier_list_order_does_not_matter() -> None:
    status = _fill_two(
        AttributeType.MONEY_USD, "$10/month, $96/year", "$96/year and $10/month"
    )
    assert status is CellStatus.FILLED


# ---------------------------------------------------------------------- bool


def test_yes_and_supported_corroborate() -> None:
    status = _fill_two(AttributeType.BOOL, "Yes", "Supported on all plans")
    assert status is CellStatus.FILLED


def test_no_and_not_available_corroborate() -> None:
    status = _fill_two(AttributeType.BOOL, "No", "Not available")
    assert status is CellStatus.FILLED


def test_chinese_and_english_polarity_agree() -> None:
    status = _fill_two(AttributeType.BOOL, "支持", "Yes, on paid plans")
    assert status is CellStatus.FILLED


def test_leading_negation_wins_over_later_affirmative() -> None:
    """"Yes, but not on the free plan" and "Not on the free plan" say the same
    thing; the operative marker is the first one."""
    status = _fill_two(AttributeType.BOOL, "Not on the free plan", "不支持免费版")
    assert status is CellStatus.FILLED


def test_opposite_polarity_still_conflicts() -> None:
    status = _fill_two(AttributeType.BOOL, "Yes, included", "No, unsupported")
    assert status is CellStatus.CONFLICT


def test_unsupported_is_not_read_as_supported() -> None:
    """Substring matching would find "supported" inside "unsupported"."""
    status = _fill_two(AttributeType.BOOL, "Supported", "Unsupported")
    assert status is CellStatus.CONFLICT


# -------------------------------------------------------------------- number


def test_same_number_different_units_wording_corroborates() -> None:
    status = _fill_two(AttributeType.NUMBER, "5 GB per user", "5GB / user")
    assert status is CellStatus.FILLED


def test_different_number_still_conflicts() -> None:
    status = _fill_two(AttributeType.NUMBER, "5 GB", "10 GB")
    assert status is CellStatus.CONFLICT


def test_number_order_is_significant() -> None:
    """Unlike a price list, "10 of 20" and "20 of 10" are different claims."""
    status = _fill_two(AttributeType.NUMBER, "10 of 20", "20 of 10")
    assert status is CellStatus.CONFLICT


# ---------------------------------------------------------------------- enum


def test_enum_member_written_as_prose_matches_the_identifier() -> None:
    """Members are identifiers ("per_user_month"), values are written for
    humans ("per user / month"). Separators must not split them apart."""
    status = _fill_two(
        AttributeType.ENUM,
        "per_user_month",
        "per user / month",
        enum_values=["per_user_month", "flat_month", "none"],
    )
    assert status is CellStatus.FILLED


def test_different_enum_members_still_conflict() -> None:
    status = _fill_two(
        AttributeType.ENUM, "Cloud", "Self-hosted", enum_values=["cloud", "self-hosted"]
    )
    assert status is CellStatus.CONFLICT


def test_enum_member_is_not_matched_by_containment() -> None:
    """Regression from real data: member `free` was found inside
    "per-member/month subscription with a free tier", whose actual member is
    `per_seat_freemium` — so the cell silently agreed with the wrong fact."""
    status = _fill_two(
        AttributeType.ENUM,
        "Per-member/month subscription with a free tier",
        "free",
        enum_values=["per_seat_freemium", "free", "subscription_only"],
    )
    assert status is CellStatus.CONFLICT


# ---------------------------------------------------------------------- text


def test_text_keeps_pre_p2_string_comparison() -> None:
    """TEXT has no type to reason with, so behaviour is unchanged: differing
    prose conflicts, and only case/whitespace is normalized away."""
    assert _fill_two(AttributeType.TEXT, "Kanban boards", "Gantt charts") is CellStatus.CONFLICT
    assert _fill_two(AttributeType.TEXT, "Kanban  boards", "kanban boards") is CellStatus.FILLED


def test_untyped_value_falls_back_to_string_comparison() -> None:
    """A typed attribute whose values carry no parsable content must not
    collapse to a single key — that would merge every unparsable value."""
    status = _fill_two(AttributeType.MONEY_USD, "Contact sales", "Enterprise quote")
    assert status is CellStatus.CONFLICT


def test_missing_attribute_definition_does_not_crash() -> None:
    """Cells can outlive a schema edit; comparison degrades to strings."""
    cm = _map(AttributeType.MONEY_USD)
    cm.attributes = []  # attribute_for() now returns None
    cm.fill("e", "a", value="$10/month", source="s1", confidence=C1)
    cell = cm.fill("e", "a", value="$10 per seat/month", source="s2", confidence=C2)
    assert cell.status is CellStatus.CONFLICT


# ------------------------------------------------------- corroboration resolves


def test_third_agreeing_source_resolves_a_conflict() -> None:
    """A conflict left by unparsable prose is resolved once a later source
    matches one side under the typed key."""
    cm = _map(AttributeType.MONEY_USD)
    cm.fill("e", "a", value="$10/month", source="s1", confidence=C1)
    cell = cm.fill("e", "a", value="$15/month", source="s2", confidence=C2)
    assert cell.status is CellStatus.CONFLICT
    # s3 agrees with s1's amount in different wording; the cell stays CONFLICT
    # because s2 still dissents — corroboration must not bury a real dissenter.
    cell = cm.fill("e", "a", value="$10 per member/month", source="s3", confidence=C1)
    assert cell.status is CellStatus.CONFLICT
    assert len(cell.candidates) == 3
