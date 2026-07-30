"""ScoreDeltaGate copied from Poirot promotion gate.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/evolution/gates/score_delta_gate.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: local eval types; min_delta=0 and hard-failure/CAPTURED rules unchanged.
"""
from __future__ import annotations

from ....domain.evolution.evolution_types import EvalResult, GateDecision
from ....domain.evolution.skill_types import SkillRecord


class ScoreDeltaGate:
    def __init__(self, min_delta: float = 0.0) -> None:
        self._min_delta = min_delta

    def decide(self, candidate: SkillRecord, baseline: SkillRecord | None, eval_result: EvalResult) -> GateDecision:
        if eval_result.hard_failures:
            return GateDecision("reject", f"hard_failures: {eval_result.hard_failures}")
        if baseline is None:
            return (GateDecision("accept", f"CAPTURED score={eval_result.score:.2f}", candidate.skill_id)
                    if eval_result.score > 0 else GateDecision("reject", "CAPTURED score=0"))
        baseline_score = self._baseline_score(eval_result)
        if eval_result.score > baseline_score + self._min_delta:
            return GateDecision("accept", f"candidate={eval_result.score:.2f} > baseline={baseline_score:.2f}", candidate.skill_id)
        return GateDecision("reject", f"candidate={eval_result.score:.2f} <= baseline={baseline_score:.2f}")

    @staticmethod
    def _baseline_score(eval_result: EvalResult) -> float:
        if not eval_result.evidence:
            return 0.0
        return sum(e.baseline_pass for e in eval_result.evidence) / len(eval_result.evidence)


__all__ = ["ScoreDeltaGate"]
