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

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# Confidence delta below which conflicting values are kept as `conflict`
# (both candidates retained) rather than letting the higher-confidence one
# win outright. ADR 0010 D-S3.
CONFLICT_CONFIDENCE_DELTA = 0.2


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

        if cell.status == CellStatus.EMPTY:
            cell.status = CellStatus.FILLED
            cell.value = value
            cell.source = source
            cell.source_excerpt = source_excerpt
            cell.confidence = confidence
            return cell

        if cell.status == CellStatus.UNKNOWN:
            # A prior attempt found nothing; a new value fills it.
            cell.status = CellStatus.FILLED
            cell.value = value
            cell.source = source
            cell.source_excerpt = source_excerpt
            cell.confidence = confidence
            cell.attempts = 0
            return cell

        # Existing value present (filled or conflict) — compare.
        existing_value = _normalize_value(cell.value)
        new_value = _normalize_value(value)
        if existing_value == new_value:
            # Support: keep filled, bump confidence.
            cell.confidence = max(cell.confidence, confidence)
            if cell.status == CellStatus.CONFLICT:
                cell.candidates.append(candidate)
                # Re-check if all candidates now agree (conflict resolved).
                if _all_candidates_agree(cell.candidates):
                    cell.status = CellStatus.FILLED
            return cell

        # Conflicting value: retain candidates and arbitrate.
        if cell.status == CellStatus.FILLED:
            cell.candidates = [
                CellCandidate(
                    value=cell.value,
                    source=cell.source,
                    source_excerpt=cell.source_excerpt,
                    confidence=cell.confidence,
                ),
                candidate,
            ]
        else:  # CONFLICT
            cell.candidates.append(candidate)

        # Arbitrate: find the highest-confidence candidate. A cell can leave
        # CONFLICT only if ONE candidate is clearly dominant (delta >= threshold
        # over EVERY other disagreeing candidate). Otherwise keep CONFLICT so
        # dissenting values are never silently buried (ADR 0010 D-S3).
        best = max(cell.candidates, key=lambda c: c.confidence)
        if _candidate_dominates(best, cell.candidates, CONFLICT_CONFIDENCE_DELTA):
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
        return cell

    def mark_unknown(self, entity_id: str, attribute_id: str) -> Cell:
        """Mark a cell as searched-but-not-found (terminal for dispatch).

        Only transitions EMPTY→UNKNOWN (a filled/conflict cell stays as-is).
        ``attempts`` counts mark_unknown calls on empty/unknown cells only.
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

    def to_projection(self) -> dict[str, Any]:
        """Read-only snapshot for SQLite projection (F-R13 coverage sub-field)."""
        total = len(self.cells)
        filled = self.filled_count()
        return {
            "filled": filled,
            "total": total,
            "pending_cells": total - filled,
            "ratio": round(self.coverage_ratio(), 4),
        }


def _normalize_value(value: str) -> str:
    """Normalize a value for same/different comparison (case + whitespace)."""
    return " ".join(value.lower().split())


def _all_candidates_agree(candidates: list[CellCandidate]) -> bool:
    """True if every candidate normalizes to the same value."""
    if not candidates:
        return True
    first = _normalize_value(candidates[0].value)
    return all(_normalize_value(c.value) == first for c in candidates[1:])


def _candidate_dominates(
    best: CellCandidate,
    candidates: list[CellCandidate],
    delta: float,
) -> bool:
    """True if `best` beats every DISAGREEING candidate by >= delta confidence.

    Agreement candidates (same normalized value) don't block dominance — they
    corroborate. Only dissenting values prevent a FILLED outcome.
    """
    best_value = _normalize_value(best.value)
    for c in candidates:
        if c is best:
            continue
        if _normalize_value(c.value) == best_value:
            continue  # corroborating, not dissenting
        if best.confidence - c.confidence < delta:
            return False  # too close to a dissenter → keep CONFLICT
    return True


__all__ = [
    "CONFLICT_CONFIDENCE_DELTA",
    "Attribute",
    "AttributeType",
    "Cell",
    "CellCandidate",
    "CellStatus",
    "CoverageMap",
    "Entity",
    "EntityType",
]
