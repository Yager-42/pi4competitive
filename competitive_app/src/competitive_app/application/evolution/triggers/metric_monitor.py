"""MetricMonitorTrigger copied/adapted from Poirot.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/evolution/triggers/metric_monitor.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: async App store and only FIX output; DERIVED/manual capture remain
unreachable per frozen workflow contract; fallback/completion rules remain fixed and
the configured threshold controls effective-rate diagnosis.
"""
from __future__ import annotations

import inspect
from typing import Any

from ....domain.evolution.evolution_types import EvolutionContext
from ....domain.evolution.skill_types import SkillRecord

_FALLBACK_THRESHOLD = 0.4
_LOW_COMPLETION_THRESHOLD = 0.35
_HIGH_APPLIED_FOR_FIX = 0.4
_MIN_APPLIED_FOR_DERIVED = 0.25


class MetricMonitorTrigger:
    def __init__(self, threshold: float = 0.3, min_selections: int = 5, cooldown_turns: int = 10, llm: Any | None = None) -> None:
        self._threshold = threshold
        self._min_selections = min_selections
        self._cooldown_turns = cooldown_turns
        self._llm = llm
        self._last_evolve_selections: dict[str, int] = {}

    async def should_trigger(self, store: Any) -> list[EvolutionContext]:
        contexts: list[EvolutionContext] = []
        records = await store.list_active()
        for record in records:
            if not record.enabled or record.total_selections < self._min_selections:
                continue
            last = self._last_evolve_selections.get(record.name, 0)
            if record.total_selections - last < self._cooldown_turns:
                continue
            kind, direction = self._diagnose_skill_health(record)
            if kind != "FIX":
                continue
            if self._llm is not None and not await self._llm_confirm_evolution(record, direction):
                continue
            contexts.append(EvolutionContext("METRIC", "FIX", record, fix_direction=direction))
        return contexts

    def mark_evolved(self, skill_name: str, total_selections: int) -> None:
        self._last_evolve_selections[skill_name] = total_selections

    def _diagnose_skill_health(self, record: SkillRecord) -> tuple[str | None, str]:
        if record.fallback_rate > _FALLBACK_THRESHOLD:
            return "FIX", f"高 fallback_rate({record.fallback_rate:.0%})：skill 常被选但未应用，指令不清或过时。"
        if record.applied_rate > _HIGH_APPLIED_FOR_FIX and record.completion_rate < _LOW_COMPLETION_THRESHOLD:
            return "FIX", f"低 completion_rate({record.completion_rate:.0%}) 但高 applied_rate({record.applied_rate:.0%})：skill 指令可能错或不全。"
        if record.effective_rate < self._threshold and record.applied_rate > _MIN_APPLIED_FOR_DERIVED:
            return "DERIVED", f"中等 effective_rate({record.effective_rate:.0%})：可派生增强版。"
        return None, ""

    async def _llm_confirm_evolution(self, record: SkillRecord, direction: str) -> bool:
        prompt = f"Skill: {record.name}\n诊断: {direction}\n只回答 yes 或 no。"
        try:
            if hasattr(self._llm, "complete_simple"):
                value = self._llm.complete_simple(prompt)
            elif hasattr(self._llm, "invoke"):
                value = self._llm.invoke(prompt)
            else:
                return False
            if inspect.isawaitable(value):
                value = await value
            return "yes" in str(getattr(value, "content", value)).lower()
        except Exception:
            return False


__all__ = ["MetricMonitorTrigger"]
