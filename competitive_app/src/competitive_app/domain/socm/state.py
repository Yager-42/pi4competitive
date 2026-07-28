"""SOCM top-level container — the search state of truth.

research-workflow-v1 v0.2.0 F-R27 / ADR 0010 D-S4. Holds the four SOCM
components. Persisted as `data/sessions/<session_id>/search_state.json` via
SocmStore (adapter/out/persistence). Pydantic model_dump/model_validate is
the snapshot/restore mechanism (SearchOS delegates the same to WorkspaceManager).

Pure domain (G1): no IO here — persistence lives in adapter/out.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .coverage import CoverageMap
from .evidence import EvidenceGraph
from .frontier import Frontier
from .strategy import Budget, StrategyMemory


class SOCMState(BaseModel):
    """Top-level SOCM: coverage + evidence + frontier + strategy + budget."""

    intent: str = ""                    # research brief goal (for judge context)
    coverage_map: CoverageMap = Field(default_factory=CoverageMap)
    evidence_graph: EvidenceGraph = Field(default_factory=EvidenceGraph)
    frontier: Frontier = Field(default_factory=Frontier)
    strategy: StrategyMemory = Field(default_factory=StrategyMemory)
    budget: Budget = Field(default_factory=Budget)
    # Orchestrator outer-loop iteration count (drives no-progress detection).
    iteration: int = 0
    # consecutive iterations with no new filled cells (F-R31 condition 3).
    stalled_iterations: int = 0

    def snapshot(self) -> dict[str, Any]:
        """Serialize for persistence (model_dump)."""
        return self.model_dump(mode="json")

    @classmethod
    def restore(cls, data: dict[str, Any]) -> SOCMState:
        """Rebuild from persisted JSON (model_validate)."""
        return cls.model_validate(data)

    def coverage_ratio(self) -> float:
        return self.coverage_map.coverage_ratio()

    def to_projection(self) -> dict[str, Any]:
        """Read-only projection snapshot for SQLite (F-R13 coverage sub-field)."""
        return {
            "coverage": self.coverage_map.to_projection(),
            "evidence": self.evidence_graph.to_projection(),
            "frontier": self.frontier.to_projection(),
            "budget": self.budget.to_projection(),
            "iteration": self.iteration,
            "stalled": self.stalled_iterations,
        }


__all__ = ["SOCMState"]
