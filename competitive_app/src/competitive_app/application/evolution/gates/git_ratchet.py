"""GitRatchet adapted from Poirot post-activation rollback monitor.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/evolution/gates/git_ratchet.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: async app store and no git commands; RuntimeTracker remains advisory.
"""
from __future__ import annotations

from typing import Any

from ....domain.evolution.skill_types import SkillRecord


class GitRatchet:
    def __init__(self, degradation_threshold: float = 0.3, min_selections: int = 5, runtime_tracker: Any | None = None) -> None:
        self._threshold = degradation_threshold
        self._min_selections = min_selections
        self._runtime_tracker = runtime_tracker

    async def check_and_rollback(self, store: Any, current: SkillRecord) -> str | None:
        if current.total_selections < self._min_selections or current.effective_rate >= self._threshold:
            return None
        versions = await store.get_versions(current.name)
        parent_ids = current.lineage.parent_skill_ids
        parent = next((v for v in versions if v.skill_id in parent_ids), None)
        if parent is None:
            others = [v for v in versions if v.skill_id != current.skill_id]
            parent = min(others, key=lambda v: v.lineage.generation) if others else None
        if parent is None:
            return None
        await store.rollback(parent.skill_id)
        return parent.skill_id


__all__ = ["GitRatchet"]
