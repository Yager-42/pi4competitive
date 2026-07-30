"""Poirot evolution value objects.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/evolution/types.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: import path and optional workflow scope on the host context. DERIVED
is retained only for persistence round-trip; no public trigger/mutator path emits it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .skill_types import SkillMetrics, SkillRecord

TriggerType = Literal["METRIC", "CAPTURE", "PERIODIC", "TOOL_DEGRADATION", "ANALYSIS"]
EvolutionType = Literal["FIX", "DERIVED", "CAPTURED"]
FailureClass = Literal["FUNDAMENTAL", "IMPLEMENTATION"]
GateRecommendation = Literal["accept_new_best", "accept", "reject", "pending_human"]
EvalMetric = Literal["hard", "soft", "mixed"]
EvalEvidenceKind = Literal["programmatic_rule", "longitudinal_pair", "judge_reason"]


@dataclass(frozen=True)
class FailureEvidence:
    turn_index: int | None
    tool_name: str | None
    failure_class: FailureClass
    description: str
    impl_fail_count: int = 0


@dataclass(frozen=True)
class EvolutionContext:
    trigger: TriggerType
    evolution_type: EvolutionType
    target_skill: SkillRecord | None
    failure_evidence: tuple[FailureEvidence, ...] = ()
    fix_direction: str = ""
    capture_pattern: str = ""
    suggested_name: str = ""
    recent_analyses: tuple[str, ...] = ()
    scope: str | None = None
    observation_id: str | None = None


@dataclass(frozen=True)
class EvalContext:
    baseline: SkillRecord | None
    candidate: SkillRecord
    metrics_baseline: SkillMetrics | None = None
    replay_samples: tuple[Any, ...] = ()
    task_domain: str | None = None


@dataclass(frozen=True)
class EvalEvidence:
    kind: EvalEvidenceKind
    rule_name: str
    baseline_pass: bool
    candidate_pass: bool
    detail: str = ""


@dataclass(frozen=True)
class EvalResult:
    score: float
    metric: EvalMetric = "hard"
    hard_failures: tuple[str, ...] = ()
    evidence: tuple[EvalEvidence, ...] = ()
    confidence: float = 0.7
    recommendation: GateRecommendation = "reject"


@dataclass(frozen=True)
class GateDecision:
    recommendation: GateRecommendation
    reason: str
    new_version_id: str | None = None


@dataclass(frozen=True)
class EvolutionRecord:
    evolution_id: str
    skill_name: str
    evolution_type: EvolutionType
    trigger: TriggerType
    baseline_id: str | None
    candidate_id: str
    failure_focus: str
    mutation_diff: str
    eval_score: float
    gate_decision: GateRecommendation
    created_version_id: str | None = None
    timestamp: str = ""


__all__ = [
    "TriggerType", "EvolutionType", "FailureClass", "GateRecommendation",
    "EvalMetric", "EvalEvidenceKind", "FailureEvidence", "EvolutionContext",
    "EvalContext", "EvalEvidence", "EvalResult", "GateDecision", "EvolutionRecord",
]
