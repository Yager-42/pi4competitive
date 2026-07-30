"""Async analyzer protocol contracts adapted from Poirot eval/protocols.py.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/eval/protocols.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: local domain types and async App adapter contracts.
"""
from __future__ import annotations
from typing import Any, Protocol
from .....domain.evolution.evolution_types import EvalResult
from .....domain.evolution.eval_types import EvolutionSuggestion, SkillHealthReport, SkillJudgment, TaskQualityScore

class SkillJudgmentAnalyzerProtocol(Protocol):
    async def analyze_execution(self, task_id: str, journal_events: list[dict], messages_summary: str,
                                injected_skills: list[dict], task_completed: bool = True) -> tuple[list[SkillJudgment], list[EvolutionSuggestion]]: ...

class TaskQualityJudgeProtocol(Protocol):
    async def judge_task(self, task_id: str, execution_trace: str, final_output: str) -> TaskQualityScore | None: ...

class ResponseContractCheckerProtocol(Protocol):
    def check(self, candidate_content: str, baseline_content: str) -> EvalResult: ...

class RuntimeTrackerProtocol(Protocol):
    async def health_report(self, skill_id: str, window: int = 20) -> SkillHealthReport: ...
    async def degraded_skills(self, threshold: float = 0.15) -> list[str]: ...

__all__ = ["SkillJudgmentAnalyzerProtocol", "TaskQualityJudgeProtocol", "ResponseContractCheckerProtocol", "RuntimeTrackerProtocol"]
