"""RuntimeTracker adapted from Poirot trend evaluation.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/eval/runtime_tracker.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: async store calls; trend is advisory and never independently rolls
back a Skill.
"""
from __future__ import annotations

from typing import Any

from ....domain.evolution.eval_types import SkillHealthReport, SkillJudgment, Trend

_MIN_JUDGMENTS_FOR_TREND = 4


class RuntimeTracker:
    def __init__(self, store: Any, degradation_delta: float = 0.15) -> None:
        self._store = store
        self._degradation_delta = degradation_delta

    async def health_report(self, skill_id: str, window: int = 20) -> SkillHealthReport:
        metrics = await self._store.get_metrics(skill_id)
        judgments = await self._store.get_judgments(skill_id, window)
        if metrics is None:
            return SkillHealthReport(skill_id, "", 0, 0.0, 0.0, 0.0, 0.0, "insufficient_data")
        trend = self._compute_trend(judgments, self._degradation_delta)
        record = await self._store.get(skill_id)
        return SkillHealthReport(
            skill_id=skill_id,
            skill_name=record.name if record else "",
            window_selections=metrics.selections,
            applied_rate=metrics.applied_rate,
            completion_rate=metrics.completion_rate,
            effective_rate=metrics.effective_rate,
            fallback_rate=metrics.fallback_rate,
            trend=trend,
            recent_judgments=tuple(judgments[:5]),
            advice=self._build_advice(metrics, trend),
        )

    async def degraded_skills(self, threshold: float = 0.15) -> list[str]:
        result: list[str] = []
        for record in await self._store.list_active():
            judgments = await self._store.get_judgments(record.skill_id, 20)
            if self._compute_trend(judgments, threshold) == "degrading":
                result.append(record.skill_id)
        return result

    @staticmethod
    def _compute_trend(judgments: list[SkillJudgment], delta: float) -> Trend:
        if len(judgments) < _MIN_JUDGMENTS_FOR_TREND:
            return "insufficient_data"
        middle = len(judgments) // 2
        recent, older = judgments[:middle], judgments[middle:]
        recent_rate = sum(j.skill_applied for j in recent) / len(recent)
        older_rate = sum(j.skill_applied for j in older) / len(older)
        difference = recent_rate - older_rate
        if difference > delta:
            return "improving"
        if difference < -delta:
            return "degrading"
        return "stable"

    @staticmethod
    def _build_advice(metrics: Any, trend: Trend) -> str:
        parts: list[str] = []
        if trend == "insufficient_data":
            parts.append("数据不足，需更多任务积累")
        if metrics.fallback_rate > 0.4:
            parts.append("fallback_rate 高，skill 触发条件可能有问题")
        if metrics.applied_rate < 0.3 and metrics.selections > 5:
            parts.append("applied_rate 低，skill 被选中但未被应用")
        if metrics.completion_rate < 0.35 and metrics.applied > 3:
            parts.append("completion_rate 低，skill 指导可能无效")
        if trend == "degrading":
            parts.append("趋势退化，建议 GitRatchet 回滚或进化修复")
        if trend == "improving":
            parts.append("趋势改善，进化效果良好")
        return "；".join(parts) if parts else "健康状态正常"


__all__ = ["RuntimeTracker"]
