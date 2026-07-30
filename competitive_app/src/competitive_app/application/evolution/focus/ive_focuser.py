"""IVEFocuser adapted from Poirot five-question failure diagnosis.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/evolution/focus/ive_focuser.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: async store/Pi adapter; evidence remains ordinary workflow data.
"""
from __future__ import annotations

import inspect
import json
from dataclasses import replace
from typing import Any

from ....domain.evolution.evolution_types import EvolutionContext, FailureEvidence


class IVEFocuser:
    def __init__(self, llm: Any | None = None, impl_fail_threshold: int = 3) -> None:
        self._llm = llm
        self._impl_fail_threshold = impl_fail_threshold
        self._impl_fail_counts: dict[str, int] = {}

    async def focus(self, ctx: EvolutionContext, store: Any) -> EvolutionContext:
        if not ctx.failure_evidence:
            return ctx
        judgment_notes: list[str] = []
        if store is not None and ctx.target_skill is not None:
            try:
                judgments = await store.get_judgments(ctx.target_skill.skill_id, 10)
                judgment_notes = [j.deviation_note for j in judgments if j.deviation_note]
            except Exception:
                pass
        if self._llm is None:
            return self._degrade(ctx, judgment_notes)
        skill_name = ctx.target_skill.name if ctx.target_skill else ctx.suggested_name
        failure_class, direction = await self._diagnose(ctx, skill_name, judgment_notes)
        count = self._impl_fail_counts.get(skill_name, 0)
        if failure_class == "IMPLEMENTATION":
            count += 1
            self._impl_fail_counts[skill_name] = count
            if count >= self._impl_fail_threshold:
                failure_class = "FUNDAMENTAL"
                direction = f"[升级 fundamental] implementation 累计 {count} 次。 {direction}"
        elif failure_class == "FUNDAMENTAL":
            self._impl_fail_counts[skill_name] = 0
        updated = tuple(FailureEvidence(e.turn_index, e.tool_name, failure_class, e.description,
                                        self._impl_fail_counts.get(skill_name, 0)) for e in ctx.failure_evidence)
        return replace(ctx, failure_evidence=updated, fix_direction=direction)

    @staticmethod
    def _degrade(ctx: EvolutionContext, notes: list[str]) -> EvolutionContext:
        parts = [e.description for e in ctx.failure_evidence]
        if notes:
            parts.extend(notes)
        return replace(ctx, fix_direction="LLM 未启用，降级全量摘要。" + " | ".join(parts))

    async def _diagnose(self, ctx: EvolutionContext, name: str, notes: list[str]) -> tuple[str, str]:
        evidence = "\n".join(f"- {e.description}" for e in ctx.failure_evidence)
        prompt = (
            f"Skill: {name}\n失败证据:\n{evidence}\n"
            f"历史偏差:\n{' | '.join(notes)}\n"
            'Return only JSON: {"class":"FUNDAMENTAL|IMPLEMENTATION","direction":"..."}'
        )
        try:
            if hasattr(self._llm, "complete_json"):
                data = self._llm.complete_json(prompt)
            elif hasattr(self._llm, "complete_simple"):
                data = self._llm.complete_simple(prompt)
            else:
                data = self._llm.invoke(prompt)
            if inspect.isawaitable(data):
                data = await data
            data = getattr(data, "content", data)
            if isinstance(data, str):
                start, end = data.find("{"), data.rfind("}")
                data = json.loads(data[start : end + 1]) if start >= 0 and end > start else {}
            cls = data.get("class", "IMPLEMENTATION") if isinstance(data, dict) else "IMPLEMENTATION"
            return (cls if cls in {"FUNDAMENTAL", "IMPLEMENTATION"} else "IMPLEMENTATION",
                    str(data.get("direction", "")) if isinstance(data, dict) else "")
        except Exception:
            return "IMPLEMENTATION", ""


__all__ = ["IVEFocuser"]
