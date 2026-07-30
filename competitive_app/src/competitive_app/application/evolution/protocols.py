"""Evolution protocols adapted from Poirot with async App boundaries.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/evolution/protocols.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: protocol methods touching store/LLM may be async; no manual-capture
protocol is exposed.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ...domain.evolution.evolution_types import EvalContext, EvalResult, EvolutionContext, GateDecision
from ...domain.evolution.skill_types import SkillRecord


@runtime_checkable
class Trigger(Protocol):
    async def should_trigger(self, store: Any) -> list[EvolutionContext]: ...


@runtime_checkable
class FailureFocuser(Protocol):
    async def focus(self, ctx: EvolutionContext, store: Any) -> EvolutionContext: ...


@runtime_checkable
class Mutator(Protocol):
    async def mutate(self, ctx: EvolutionContext, llm: Any | None = None) -> tuple[SkillRecord, str]: ...


@runtime_checkable
class EvalBridge(Protocol):
    async def evaluate(self, ctx: EvalContext) -> EvalResult: ...


@runtime_checkable
class PromotionGate(Protocol):
    def decide(self, candidate: SkillRecord, baseline: SkillRecord | None, eval_result: EvalResult) -> GateDecision: ...


__all__ = ["Trigger", "FailureFocuser", "Mutator", "EvalBridge", "PromotionGate"]
