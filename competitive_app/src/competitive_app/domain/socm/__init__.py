"""SOCM — Search-Oriented Context Management (research-workflow-v1 v0.2.0).

Pure domain models (G1): no fastapi / aiosqlite / pi_agent / pi_ai imports.
Pydantic v2 only. Architecture reference (not code): SearchOS searchos/socm/.

Four components (ADR 0010 D-S3/D-S4):
- CoverageMap: entity × attribute table, four-state cells (empty/filled/unknown/conflict)
- EvidenceGraph: findings + support/conflict edges
- Frontier: task queue with priority + blocked_by DAG
- StrategyMemory + Budget: failure memory + 5-dimension consumable budget

Top-level container: SOCMState. Persisted via adapter/out/persistence/socm_store.
"""
from __future__ import annotations

from .coverage import (
    CONFLICT_CONFIDENCE_DELTA,
    Attribute,
    AttributeType,
    Cell,
    CellCandidate,
    CellStatus,
    CoverageMap,
    Entity,
    EntityType,
)
from .evidence import (
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
    EvidenceRelation,
    EvidenceStatus,
)
from .frontier import (
    MAX_FRONTIER_CAP,
    MAX_FRONTIER_DEPTH,
    MAX_TASK_ATTEMPTS,
    Frontier,
    FrontierTask,
    FrontierTaskStatus,
)
from .state import SOCMState
from .strategy import (
    AntiPatternKind,
    Budget,
    StrategyMemory,
    StrategyPattern,
)

__all__ = [
    "CONFLICT_CONFIDENCE_DELTA",
    "MAX_FRONTIER_CAP",
    "MAX_FRONTIER_DEPTH",
    "MAX_TASK_ATTEMPTS",
    "AntiPatternKind",
    "Attribute",
    "AttributeType",
    "Budget",
    "Cell",
    "CellCandidate",
    "CellStatus",
    "CoverageMap",
    "Entity",
    "EntityType",
    "EvidenceEdge",
    "EvidenceGraph",
    "EvidenceNode",
    "EvidenceRelation",
    "EvidenceStatus",
    "Frontier",
    "FrontierTask",
    "FrontierTaskStatus",
    "SOCMState",
    "StrategyMemory",
    "StrategyPattern",
]
