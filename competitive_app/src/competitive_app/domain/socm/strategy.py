"""SOCM Strategy Memory + Budget — failure memory + 5-dimension budget.

research-workflow-v1 v0.2.0 F-R31 / ADR 0010 D-S8. Budget tracks 5 consumable
dimensions (queries/opens/fetches/iterations/wall_seconds); `exhausted` is
True when any dimension's ratio >= 1.0 (max across dimensions, matching
SearchOS state.py:BudgetState). SEARCH_MAX_PARALLEL is a concurrency cap,
NOT a budget dimension (ADR 0010 D-S8).

Pure domain (G1). Reference (architecture only): SearchOS searchos/socm/strategy.py
(StrategyMemory = anti-pattern store) + searchos/socm/state.py (BudgetState).
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AntiPatternKind(str, Enum):
    QUERY = "query"
    SOURCE = "source"
    BRANCH = "branch"
    CLAIM = "claim"


class StrategyPattern(BaseModel):
    """A proven-ineffective pattern (avoid repeating)."""

    id: str
    kind: AntiPatternKind = AntiPatternKind.QUERY
    signature: str = ""        # normalized key (query text / source host / ...)
    reason: str = ""
    observed_count: int = 1


class StrategyMemory(BaseModel):
    """Anti-pattern / failure memory (not positive-strategy store)."""

    patterns: list[StrategyPattern] = Field(default_factory=list)

    def record(self, pattern: StrategyPattern) -> StrategyPattern:
        """Dedup by (kind, signature): match → bump count, new → append."""
        for p in self.patterns:
            if p.kind == pattern.kind and p.signature == pattern.signature:
                p.observed_count += 1
                return p
        self.patterns.append(pattern)
        return pattern

    def has_pattern(self, kind: AntiPatternKind, signature: str) -> bool:
        return any(
            p.kind == kind and p.signature == signature for p in self.patterns
        )

    def to_projection(self) -> dict[str, Any]:
        return {"patterns": len(self.patterns)}


class Budget(BaseModel):
    """5-dimension consumable budget (F-R31 termination condition 2).

    Each dimension: max_X (0 = disabled) + consumed_X. `exhausted` is True
    when any enabled dimension's consumption ratio >= 1.0.
    """

    max_queries: int = 40
    max_opens: int = 30
    max_fetches: int = 30
    max_iterations: int = 10
    max_wall_seconds: int = 600

    consumed_queries: int = 0
    consumed_opens: int = 0
    consumed_fetches: int = 0
    consumed_iterations: int = 0
    consumed_wall_seconds: float = 0.0

    def consume_query(self, n: int = 1) -> None:
        self.consumed_queries += n

    def consume_open(self, n: int = 1) -> None:
        # opens and fetches are the same dimension in v0.2.0 (a fetch opens a
        # page); kept distinct names to align with SearchOS BudgetState.
        self.consumed_opens += n
        self.consumed_fetches += n

    def consume_iteration(self, n: int = 1) -> None:
        self.consumed_iterations += n

    def consume_wall(self, seconds: float) -> None:
        self.consumed_wall_seconds += seconds

    def ratio(self) -> float:
        """Max consumption ratio across enabled dimensions (SearchOS convention)."""
        ratios: list[float] = []
        if self.max_queries > 0:
            ratios.append(self.consumed_queries / self.max_queries)
        if self.max_opens > 0:
            ratios.append(self.consumed_opens / self.max_opens)
        if self.max_fetches > 0:
            ratios.append(self.consumed_fetches / self.max_fetches)
        if self.max_iterations > 0:
            ratios.append(self.consumed_iterations / self.max_iterations)
        if self.max_wall_seconds > 0:
            ratios.append(self.consumed_wall_seconds / self.max_wall_seconds)
        return max(ratios) if ratios else 0.0

    def exhausted(self) -> bool:
        """Any enabled dimension at or over its cap."""
        return self.ratio() >= 1.0

    def exhausted_dim(self) -> str | None:
        """Which dimension is exhausted (for diagnostics), or None."""
        checks = [
            ("queries", self.max_queries, self.consumed_queries),
            ("opens", self.max_opens, self.consumed_opens),
            ("fetches", self.max_fetches, self.consumed_fetches),
            ("iterations", self.max_iterations, self.consumed_iterations),
            ("wall_seconds", self.max_wall_seconds, self.consumed_wall_seconds),
        ]
        for name, mx, consumed in checks:
            if mx > 0 and consumed >= mx:
                return name
        return None

    def to_projection(self) -> dict[str, Any]:
        return {
            "ratio": round(self.ratio(), 4),
            "exhausted": self.exhausted(),
            "exhausted_dim": self.exhausted_dim(),
        }


__all__ = [
    "AntiPatternKind",
    "Budget",
    "StrategyMemory",
    "StrategyPattern",
]
