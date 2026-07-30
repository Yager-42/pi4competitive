"""Pure Skill value objects transplanted from Poirot.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/types.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: package import path only; workflow scope is stored in the companion
``workflow_skill_metadata`` table rather than adding business fields to these
original records. Dataclasses and rate calculations retain upstream semantics.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SkillLineage:
    parent_skill_ids: tuple[str, ...] = ()
    generation: int = 0
    origin: str = "IMPORTED"
    version_hash: str = ""
    created_by: str | None = None


@dataclass(frozen=True)
class SkillRecord:
    skill_id: str
    name: str
    path: str
    content_hash: str
    is_active: bool = True
    lineage: SkillLineage = field(default_factory=SkillLineage)
    description: str = ""
    allowed_tools: tuple[str, ...] = ()
    enabled: bool = True
    total_selections: int = 0
    total_applied: int = 0
    total_completions: int = 0
    total_fallbacks: int = 0
    created_at: str = ""
    last_updated: str = ""

    @property
    def applied_rate(self) -> float:
        return self.total_applied / self.total_selections if self.total_selections else 0.0

    @property
    def completion_rate(self) -> float:
        return self.total_completions / self.total_applied if self.total_applied else 0.0

    @property
    def effective_rate(self) -> float:
        return self.total_completions / self.total_selections if self.total_selections else 0.0

    @property
    def fallback_rate(self) -> float:
        return self.total_fallbacks / self.total_selections if self.total_selections else 0.0


@dataclass(frozen=True)
class SkillMetrics:
    skill_id: str
    selections: int
    applied: int
    completions: int
    fallbacks: int
    applied_rate: float
    completion_rate: float
    effective_rate: float
    fallback_rate: float


@dataclass(frozen=True)
class SkillHealth:
    skill_id: str
    name: str
    effective_rate: float
    fallback_rate: float
    total_selections: int
    degraded: bool


__all__ = ["SkillLineage", "SkillRecord", "SkillMetrics", "SkillHealth"]
