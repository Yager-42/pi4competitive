"""SOCM Coverage Map — entity × attribute table with four-state cells.

research-workflow-v1 v0.2.0 F-R26 / ADR 0010 D-S3. Single-table (v0.2.0 omits
SearchOS multi-table + foreign keys). Each cell is one of four states:
empty / filled / unknown / conflict. Conflict arbitration uses a confidence
delta threshold (CONFLICT_CONFIDENCE_DELTA, default 0.2).

Pure domain (G1): no fastapi / aiosqlite / pi_agent / pi_ai. Pydantic only.

Reference (architecture only, not code): SearchOS searchos/socm/coverage.py.
SearchOS uses status + has_conflict flag; v0.2.0 collapses to a four-state
enum for simpler write-stage rendering.
"""
from __future__ import annotations

import re
from enum import Enum
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field

# Confidence delta below which conflicting values are kept as `conflict`
# (both candidates retained) rather than letting the higher-confidence one
# win outright. ADR 0010 D-S3.
CONFLICT_CONFIDENCE_DELTA = 0.2

# Confidence below which a FILLED cell is "weak" and eligible for re-search
# (actionable_cells / satisfied_ratio, ADR 0010 D-S8 Tier-0/1 fix). A finding
# must clear SEARCH_MIN_CONFIDENCE to be FILLED at all (extraction.py), so a
# FILLED cell with confidence in [MIN_CONFIDENCE, WEAK_CONFIDENCE) is a
# low-but-acceptable value worth corroborating.
WEAK_CONFIDENCE = 0.7


class CellStatus(str, Enum):
    """Four cell states (F-R26)."""

    EMPTY = "empty"        # not yet searched
    FILLED = "filled"      # has a value (with source + confidence)
    UNKNOWN = "unknown"    # searched, no value found (tracks attempts)
    CONFLICT = "conflict"  # multiple sources disagree (candidates retained)


class EntityType(str, Enum):
    TARGET = "target"
    COMPETITOR = "competitor"


class Entity(BaseModel):
    """A row in the coverage table (target or competitor)."""

    id: str
    name: str
    kind: EntityType = EntityType.COMPETITOR


class AttributeType(str, Enum):
    """Closed enum of attribute types (F-R26).

    Extraction normalizes values by type; write formats by type.
    """

    TEXT = "text"
    MONEY_USD = "money_usd"
    BOOL = "bool"
    NUMBER = "number"
    ENUM = "enum"


class Attribute(BaseModel):
    """A column in the coverage table, expanded from a brief dimension."""

    id: str
    name: str
    dimension: str
    type: AttributeType = AttributeType.TEXT
    # For enum type: the allowed values. Empty for other types.
    enum_values: list[str] = Field(default_factory=list)
    validation: str = "non_empty"


class CellCandidate(BaseModel):
    """One source's claim for a cell (used in conflict state)."""

    value: str
    source: str
    source_excerpt: str = ""
    confidence: float = 0.5


class Cell(BaseModel):
    """One entity × attribute cell (F-R26 four-state)."""

    entity_id: str
    attribute_id: str
    status: CellStatus = CellStatus.EMPTY

    # filled fields
    value: str = ""
    source: str = ""
    source_excerpt: str = ""
    confidence: float = 0.0

    # unknown fields
    attempts: int = 0

    # conflict fields
    candidates: list[CellCandidate] = Field(default_factory=list)

    def is_terminal(self) -> bool:
        """A cell that should not be re-dispatched (filled/unknown/conflict).

        `unknown` is terminal for dispatch (don't re-search) but write renders
        it as "no reliable source found". `conflict` is terminal (write renders
        multi-source).
        """
        return self.status in {CellStatus.FILLED, CellStatus.UNKNOWN, CellStatus.CONFLICT}


class CoverageMap(BaseModel):
    """Single-table coverage map (F-R26).

    Built from plan stage's coverage_schema. `fill()` arbitrates evidence;
    `coverage_ratio()` drives the search termination condition (F-R31).
    """

    table_id: str = "t_competitive"
    entities: list[Entity] = Field(default_factory=list)
    attributes: list[Attribute] = Field(default_factory=list)
    cells: dict[str, Cell] = Field(default_factory=dict)

    @staticmethod
    def cell_key(entity_id: str, attribute_id: str) -> str:
        return f"{entity_id}.{attribute_id}"

    @classmethod
    def from_schema(
        cls,
        *,
        table_id: str,
        entities: list[Entity],
        attributes: list[Attribute],
    ) -> CoverageMap:
        """Build an empty coverage map from plan's coverage_schema (all empty)."""
        cells: dict[str, Cell] = {}
        for entity in entities:
            for attr in attributes:
                key = cls.cell_key(entity.id, attr.id)
                cells[key] = Cell(entity_id=entity.id, attribute_id=attr.id)
        return cls(table_id=table_id, entities=list(entities), attributes=list(attributes), cells=cells)

    def get_cell(self, entity_id: str, attribute_id: str) -> Cell | None:
        return self.cells.get(self.cell_key(entity_id, attribute_id))

    def attribute_for(self, attribute_id: str) -> Attribute | None:
        """The column definition for a cell, or None if the schema omits it.

        Feeds type-aware value comparison in ``fill``. Linear over a dozen-odd
        attributes; a cached index would outlive schema edits for no real gain.
        """
        for attribute in self.attributes:
            if attribute.id == attribute_id:
                return attribute
        return None

    def empty_cells(self) -> list[Cell]:
        """Cells that still need dispatch (empty only — unknown/conflict are terminal)."""
        return [c for c in self.cells.values() if c.status == CellStatus.EMPTY]

    def fill(
        self,
        entity_id: str,
        attribute_id: str,
        *,
        value: str,
        source: str,
        source_excerpt: str = "",
        confidence: float = 0.5,
    ) -> Cell:
        """Fill a cell with a new evidence value, arbitrating conflicts (D-S3).

        Rules:
        - empty → filled directly.
        - filled, same value (normalized) → support; keep filled, confidence = max.
        - filled/unknown, different value:
          - confidence delta ≥ CONFLICT_CONFIDENCE_DELTA → higher wins (filled),
            loser recorded as conflict candidate (traceable).
          - delta < threshold → conflict state, both candidates retained.
        - conflict → append candidate, re-arbitrate.
        """
        key = self.cell_key(entity_id, attribute_id)
        cell = self.cells.get(key)
        if cell is None:
            raise KeyError(f"no cell for {key}")

        candidate = CellCandidate(
            value=value, source=source, source_excerpt=source_excerpt, confidence=confidence
        )
        # P2: same/different is decided on the attribute's own terms, so two
        # phrasings of one price ("$10 per member/month" vs "$10 per
        # seat/month") corroborate instead of registering as dissent.
        attribute = self.attribute_for(attribute_id)

        if cell.status == CellStatus.EMPTY:
            cell.status = CellStatus.FILLED
            cell.value = value
            cell.source = source
            cell.source_excerpt = source_excerpt
            cell.confidence = confidence
            if confidence < WEAK_CONFIDENCE:
                cell.attempts = 1
            return cell

        if cell.status == CellStatus.UNKNOWN:
            # A prior attempt found nothing; a new value fills it. Weak values
            # still consume this search attempt so retries eventually terminate.
            cell.status = CellStatus.FILLED
            cell.value = value
            cell.source = source
            cell.source_excerpt = source_excerpt
            cell.confidence = confidence
            cell.attempts = 1 if confidence < WEAK_CONFIDENCE else 0
            return cell

        # Existing value present (filled or conflict) — compare.
        existing_value = _comparison_key(cell.value, attribute)
        new_value = _comparison_key(value, attribute)
        if existing_value == new_value:
            # Support: keep filled, bump confidence and count another weak retry.
            if confidence > cell.confidence:
                cell.source = source
                cell.source_excerpt = source_excerpt
            cell.confidence = max(cell.confidence, confidence)
            if cell.confidence < WEAK_CONFIDENCE:
                cell.attempts += 1
            if cell.status == CellStatus.CONFLICT:
                cell.candidates.append(candidate)
                # Re-check if all candidates now agree (conflict resolved).
                if _all_candidates_agree(cell.candidates, attribute):
                    cell.status = CellStatus.FILLED
            return cell

        # Conflicting value: retain candidates and arbitrate.
        if cell.status == CellStatus.FILLED:
            # A previously resolved conflict keeps its full candidate history;
            # append new dissent instead of replacing the audit trail.
            existing_norm = _comparison_key(cell.value, attribute)
            recorded = any(
                _comparison_key(c.value, attribute) == existing_norm for c in cell.candidates
            )
            if not recorded:
                cell.candidates.append(
                    CellCandidate(
                        value=cell.value,
                        source=cell.source,
                        source_excerpt=cell.source_excerpt,
                        confidence=cell.confidence,
                    )
                )
            cell.candidates.append(candidate)
        else:  # CONFLICT
            cell.candidates.append(candidate)

        # Arbitrate: find the highest-confidence candidate. A cell can leave
        # CONFLICT only if ONE candidate is clearly dominant (delta >= threshold
        # over EVERY other disagreeing candidate). Otherwise keep CONFLICT so
        # dissenting values are never silently buried (ADR 0010 D-S3).
        best = max(cell.candidates, key=lambda c: c.confidence)
        if _candidate_dominates(best, cell.candidates, CONFLICT_CONFIDENCE_DELTA, attribute):
            cell.value = best.value
            cell.source = best.source
            cell.source_excerpt = best.source_excerpt
            cell.confidence = best.confidence
            cell.status = CellStatus.FILLED
        else:
            cell.status = CellStatus.CONFLICT
            cell.value = best.value
            cell.source = best.source
            cell.source_excerpt = best.source_excerpt
            cell.confidence = best.confidence
        if cell.status == CellStatus.FILLED and cell.confidence < WEAK_CONFIDENCE:
            cell.attempts += 1
        return cell

    def mark_unknown(self, entity_id: str, attribute_id: str) -> Cell:
        """Mark a cell as searched-but-not-found (terminal for dispatch).

        EMPTY/UNKNOWN attempts count no-result searches; weak FILLED attempts are
        counted by ``fill`` so the quality retry loop has a finite bound.
        """
        key = self.cell_key(entity_id, attribute_id)
        cell = self.cells.get(key)
        if cell is None:
            raise KeyError(f"no cell for {key}")
        if cell.status in {CellStatus.EMPTY, CellStatus.UNKNOWN}:
            cell.status = CellStatus.UNKNOWN
            cell.attempts += 1
        return cell

    def coverage_ratio(self) -> float:
        """Covered / total — F-R31 termination condition 1 (≥ 0.8).

        "Covered" = non-empty: filled, unknown, or conflict. A cell that was
        searched but found nothing (unknown) or has conflicting sources
        (conflict) still counts as covered — only empty (never-dispatched)
        cells keep the ratio below 1.0. This matches the SearchOS intent that
        recall-first dispatch keeps targeting empty cells until coverage is met.
        """
        total = len(self.cells)
        if total == 0:
            return 0.0
        covered = sum(1 for c in self.cells.values() if c.status != CellStatus.EMPTY)
        return covered / total

    def filled_count(self) -> int:
        return sum(1 for c in self.cells.values() if c.status == CellStatus.FILLED)

    def settled_claim_count(self) -> int:
        """Cells that carry a reported value (P2).

        A CONFLICT cell holds the winning value plus its dissenters and the
        write stage renders it with the disagreement attached — that is a claim
        the report makes, so counting only FILLED under-reported a
        heavily-corroborated run as having almost no claims.
        """
        return sum(
            1
            for c in self.cells.values()
            if c.value and c.status in {CellStatus.FILLED, CellStatus.CONFLICT}
        )

    def actionable_cells(self, max_attempts: int = 2) -> list[Cell]:
        """Return cells eligible for initial search or quality retries.

        Weak FILLED values are retried and their attempts are counted by ``fill``;
        this keeps the quality loop actionable while ensuring weak values eventually
        become terminal-given-up at ``max_attempts``.
        """
        actionable: list[Cell] = []
        for c in self.cells.values():
            if c.status == CellStatus.EMPTY:
                actionable.append(c)
            elif c.status == CellStatus.UNKNOWN and c.attempts < max_attempts:
                actionable.append(c)
            elif (
                c.status == CellStatus.FILLED
                and c.confidence < WEAK_CONFIDENCE
                and c.attempts < max_attempts
            ):
                actionable.append(c)
        return actionable

    def satisfied_ratio(self, max_attempts: int = 2) -> float:
        """Fraction of cells that are "done well enough" (Tier-0/1 termination condition).

        A cell is satisfied when it is:
        - FILLED with confidence >= WEAK_CONFIDENCE (strong value), OR
        - CONFLICT (multi-source already arbitrated), OR
        - terminal-given-up: UNKNOWN/FILLED[weak] with attempts >= max_attempts
          (searched enough, no better source forthcoming — stop re-searching).

        Only cells still in the actionable set (EMPTY / retryable-UNKNOWN / retryable-weak)
        keep the ratio below 1.0. This replaces the old coverage_ratio() which counted any
        non-EMPTY cell (including junk FILLED) as covered — the root cause of one-round exit.
        """
        total = len(self.cells)
        if total == 0:
            return 0.0
        satisfied = 0
        for c in self.cells.values():
            if c.status == CellStatus.CONFLICT:
                satisfied += 1
            elif c.status == CellStatus.FILLED and c.confidence >= WEAK_CONFIDENCE:
                satisfied += 1
            elif c.status in {CellStatus.UNKNOWN, CellStatus.FILLED} and c.attempts >= max_attempts:
                # terminal-given-up: searched enough, accept best-effort / no-source.
                satisfied += 1
        return satisfied / total

    def to_projection(self) -> dict[str, Any]:
        """Read-only snapshot for SQLite projection (F-R13 coverage sub-field).

        P2: one coverage口径 for the whole payload. ``pending_cells`` counts
        EMPTY only — it used to be ``total - filled``, which called terminal
        unknown/conflict cells pending while ``ratio`` in the same dict counted
        them as covered (17% vs 50% on the same run). Delegates to the
        four-state breakdown so the two can no longer disagree.
        """
        return self.to_projection_with_states()

    def to_projection_with_states(self) -> dict[str, Any]:
        """v0.3.1: four-state breakdown for GET /reports/{id} full report.

        The report page renders the four-state distribution as a pi4
        differentiator. Since P2 this is also what ``to_projection`` returns.
        """
        total = len(self.cells)
        filled = 0
        unknown = 0
        conflict = 0
        empty = 0
        for c in self.cells.values():
            if c.status == CellStatus.FILLED:
                filled += 1
            elif c.status == CellStatus.UNKNOWN:
                unknown += 1
            elif c.status == CellStatus.CONFLICT:
                conflict += 1
            else:
                empty += 1
        return {
            "filled": filled,
            "total": total,
            "unknown": unknown,
            "conflict": conflict,
            "pending_cells": empty,
            "ratio": round(self.coverage_ratio(), 4),
        }

    def to_matrix(self) -> dict[str, Any]:
        """F2: full coverage_map matrix for GET /reports/{id} + GraphPage.

        Returns entities/attributes/cells (each cell with four-state status +
        value/source/confidence/candidates). pi4 differentiator: the structured
        entity×attribute matrix (vs VerdaAI's flat evidence). SOCM stays the
        search SoT (D-S4); this is a read-only projection.
        """
        return {
            "entities": [e.model_dump(mode="json") for e in self.entities],
            "attributes": [a.model_dump(mode="json") for a in self.attributes],
            "cells": [
                {
                    "entity_id": c.entity_id,
                    "attribute_id": c.attribute_id,
                    "status": c.status.value,
                    "value": c.value,
                    "source": c.source,
                    "source_excerpt": c.source_excerpt,
                    "confidence": c.confidence,
                    "attempts": c.attempts,
                    "candidates": [cand.model_dump(mode="json") for cand in c.candidates],
                }
                for c in self.cells.values()
            ],
        }


def _normalize_value(value: str) -> str:
    """Normalize a value for same/different comparison (case + whitespace)."""
    return " ".join(value.lower().split())


#: Characters that continue a word. A marker must not be flanked by one, or
#: plain substring matching reads "no" out of "notion", "support" out of
#: "unsupported", and "mo" out of "month".
_WORD_CHARS = "a-z0-9"

#: Numbers, with thousands separators and decimals ("1,200.50" → 1200.5).
_NUMBER_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")

#: Markers that resolve a prose BOOL value to a polarity. Only unambiguous
#: ones: a missed equivalence keeps today's behaviour, while a wrong match
#: silently merges two genuinely different values. Chinese negation is listed
#: in compound form ("不支持", never bare "不") so "无限用户" stays undecided
#: instead of reading as a negation.
_BOOL_TRUE_MARKERS = (
    "yes", "true", "supported", "supports", "support", "available",
    "included", "includes", "offered", "✓", "√", "☑",
    "是", "支持", "提供", "包含", "可用",
)
_BOOL_FALSE_MARKERS = (
    "no", "not", "none", "false", "never", "unsupported", "unavailable",
    "without", "excluded", "n/a", "×", "✗", "❌",
    "否", "不支持", "不提供", "不可用", "不包含", "没有", "无法",
)

#: Billing periods that make two equal amounts different facts ($10/mo vs
#: $10/yr). Per-seat wording ("per user" / "per member" / "per seat") is
#: deliberately absent — collapsing it is the point of the money key.
_MONEY_PERIODS = (
    ("month", ("month", "monthly", "mo", "月")),
    ("year", ("year", "yearly", "annual", "annually", "yr", "年")),
)

#: Values that state a zero price without a digit. Matched as standalone tokens
#: like every other marker here, so a "Freelancer" tier is not a $0 price.
_FREE_MARKERS = ("free", "免费", "无需付费")


@lru_cache(maxsize=256)
def _marker_re(marker: str) -> re.Pattern[str]:
    """`marker`, matchable only when not flanked by word characters.

    Lookarounds rather than tokenization: markers like "n/a" and "$12/mo"
    straddle a separator, so splitting on non-word characters would either lose
    them or glue them to the adjacent digits. CJK and symbol markers pass the
    lookarounds unaffected, since they have no word boundaries to anchor to.
    """
    return re.compile(
        rf"(?<![{_WORD_CHARS}]){re.escape(marker)}(?![{_WORD_CHARS}])"
    )


def _marker_positions(normalized: str, marker: str) -> list[int]:
    """Start offsets where `marker` occurs as a standalone token."""
    return [m.start() for m in _marker_re(marker).finditer(normalized)]


def _parse_bool(normalized: str) -> bool | None:
    """Resolve a prose yes/no to a polarity, or None when undecidable.

    The EARLIEST marker wins: "yes, but not on the free plan" and "not on the
    free plan" state the same thing, and both English and Chinese put the
    operative negation ahead of its qualifier. Ties go to the longer marker.
    """
    best_index = len(normalized) + 1
    best_polarity: bool | None = None
    best_length = 0
    for markers, polarity in ((_BOOL_TRUE_MARKERS, True), (_BOOL_FALSE_MARKERS, False)):
        for marker in markers:
            for position in _marker_positions(normalized, marker):
                if position < best_index or (
                    position == best_index and len(marker) > best_length
                ):
                    best_index, best_polarity, best_length = position, polarity, len(marker)
    return best_polarity


def _numbers_in(normalized: str) -> list[float]:
    numbers: list[float] = []
    for match in _NUMBER_RE.finditer(normalized):
        try:
            numbers.append(float(match.group(0).replace(",", "")))
        except ValueError:
            continue
    return numbers


def _number_key(normalized: str) -> tuple[float, ...] | None:
    """Ordered numbers in a value, or None when it carries none.

    Order is significant here (unlike money): "10 of 20" and "20 of 10" are
    not the same claim.
    """
    numbers = _numbers_in(normalized)
    return tuple(numbers) or None


def _money_key(normalized: str) -> tuple[tuple[float, ...], frozenset[str]] | None:
    """Amounts + billing periods, or None when the value states no price.

    "$10 per member/month" and "$10 per seat/month" are one price written two
    ways; comparing amounts instead of prose stops wording from being recorded
    as source disagreement. Amounts are sorted because published tiers list
    monthly/annual in either order, but the period set is kept so $10/mo and
    $10/yr still disagree.
    """
    numbers = _numbers_in(normalized)
    if not numbers and any(
        _marker_positions(normalized, marker) for marker in _FREE_MARKERS
    ):
        numbers = [0.0]  # "free" is a stated price of zero, not a missing one
    if not numbers:
        return None
    periods = {
        name
        for name, markers in _MONEY_PERIODS
        if any(_marker_positions(normalized, marker) for marker in markers)
    }
    return tuple(sorted(numbers)), frozenset(periods)


def _enum_key(normalized: str, enum_values: list[str]) -> str | None:
    """The declared enum member a value names, or None if it names none.

    Separator-insensitive, because members are identifiers ("per_user_month")
    while values are written for humans ("per user month"). Deliberately NOT
    substring containment: on real data that matched member ``free`` inside
    "per-member/month subscription with a free tier", which is
    ``per_seat_freemium``. A missed match costs a conflict that was already
    there; a wrong one merges two different facts.
    """
    value = _canonical_identifier(normalized)
    for raw in enum_values:
        member = _canonical_identifier(_normalize_value(raw))
        if member and member == value:
            return member
    return None


def _canonical_identifier(normalized: str) -> str:
    """Collapse identifier separators so "per_user_month" == "per user/month"."""
    return re.sub(r"[\s_/\-]+", " ", normalized).strip()


def _comparison_key(value: str, attribute: Attribute | None = None) -> Any:
    """The key two values are compared on for same/different (P2).

    Pure string equality read "$10 per member/month" and "$10 per seat/month"
    as two sources contradicting each other, so corroboration was penalized:
    cells seen by one source were 100% filled, cells seen by two or more were
    77% conflict. Typed attributes compare on their own terms; TEXT and any
    value the type cannot decide fall back to the normalized string, which is
    exactly the pre-P2 behaviour.
    """
    normalized = _normalize_value(value)
    if attribute is None:
        return normalized
    if attribute.type is AttributeType.MONEY_USD:
        key: Any = _money_key(normalized)
    elif attribute.type is AttributeType.NUMBER:
        key = _number_key(normalized)
    elif attribute.type is AttributeType.BOOL:
        key = _parse_bool(normalized)
    elif attribute.type is AttributeType.ENUM:
        key = _enum_key(normalized, attribute.enum_values)
    else:
        return normalized
    return normalized if key is None else (attribute.type.value, key)


def _all_candidates_agree(
    candidates: list[CellCandidate], attribute: Attribute | None = None
) -> bool:
    """True if every candidate compares equal under the attribute's type."""
    if not candidates:
        return True
    first = _comparison_key(candidates[0].value, attribute)
    return all(_comparison_key(c.value, attribute) == first for c in candidates[1:])


def _candidate_dominates(
    best: CellCandidate,
    candidates: list[CellCandidate],
    delta: float,
    attribute: Attribute | None = None,
) -> bool:
    """True if `best` beats every DISAGREEING candidate by >= delta confidence.

    Agreement candidates (equal comparison key) don't block dominance — they
    corroborate. Only dissenting values prevent a FILLED outcome.
    """
    best_value = _comparison_key(best.value, attribute)
    for c in candidates:
        if c is best:
            continue
        if _comparison_key(c.value, attribute) == best_value:
            continue  # corroborating, not dissenting
        if best.confidence - c.confidence < delta:
            return False  # too close to a dissenter → keep CONFLICT
    return True


__all__ = [
    "CONFLICT_CONFIDENCE_DELTA",
    "WEAK_CONFIDENCE",
    "Attribute",
    "AttributeType",
    "Cell",
    "CellCandidate",
    "CellStatus",
    "CoverageMap",
    "Entity",
    "EntityType",
]
