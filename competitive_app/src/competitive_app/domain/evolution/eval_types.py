"""Poirot evaluation value objects.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/eval/types.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: import path and task evidence remains de-identified in App stores;
no benchmark/replay identity is added.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .evolution_types import EvolutionType

EvalLayer = Literal["execution", "task", "response"]
Trend = Literal["improving", "stable", "degrading", "insufficient_data"]
ContractRuleKind = Literal["programmatic", "llm_binary"]


@dataclass(frozen=True)
class SkillJudgment:
    judgment_id: str
    skill_id: str
    skill_name: str
    task_id: str
    skill_applied: bool
    deviation_note: str = ""
    timestamp: str = ""


@dataclass(frozen=True)
class EvolutionSuggestion:
    evolution_type: EvolutionType
    target_skill_ids: tuple[str, ...] = ()
    direction: str = ""


@dataclass(frozen=True)
class TaskQualityScore:
    score_id: str
    task_id: str
    task_completion: float
    response_quality: float
    efficiency: float
    tool_usage: float
    overall_score: float
    rationale: str = ""
    timestamp: str = ""


@dataclass(frozen=True)
class ContractRule:
    rule_id: str
    kind: ContractRuleKind
    hard: bool
    description: str = ""
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SkillHealthReport:
    skill_id: str
    skill_name: str
    window_selections: int
    applied_rate: float
    completion_rate: float
    effective_rate: float
    fallback_rate: float
    trend: Trend
    recent_judgments: tuple[SkillJudgment, ...] = ()
    advice: str = ""


@dataclass(frozen=True)
class EvalRun:
    eval_run_id: str
    eval_layer: EvalLayer
    skill_ids: tuple[str, ...]
    candidate_id: str | None = None
    baseline_id: str | None = None
    result_json: str = ""
    timestamp: str = ""


__all__ = [
    "EvalLayer", "Trend", "ContractRuleKind", "SkillJudgment",
    "EvolutionSuggestion", "TaskQualityScore", "ContractRule", "SkillHealthReport", "EvalRun",
]
