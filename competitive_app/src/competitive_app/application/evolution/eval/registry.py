"""Instance-level RegistryEvalBridge adapted from Poirot.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/eval/registry.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: async file reads and local eval types; empty/exception registry is
fail-closed to score 0 with a hard failure.
"""
from __future__ import annotations

import asyncio

from ....domain.evolution.evolution_types import EvalContext, EvalEvidence, EvalResult
from .analyzers import checks
from .analyzers.contract_compiler import ContractCompiler
from .analyzers.response_contract_checker import ResponseContractChecker


class EvalRegistry:
    def __init__(self, contract_checker: ResponseContractChecker | None = None) -> None:
        self._contract_checker = contract_checker

    def get_contract_checker(self) -> ResponseContractChecker:
        if self._contract_checker is None:
            raise RuntimeError("eval registry has no contract checker")
        return self._contract_checker


class RegistryEvalBridge:
    def __init__(self, registry: EvalRegistry) -> None:
        self._registry = registry

    async def evaluate(self, ctx: EvalContext) -> EvalResult:
        try:
            checker = self._registry.get_contract_checker()
            candidate = await asyncio.to_thread(checks.read_content, ctx.candidate)
            baseline = await asyncio.to_thread(checks.read_content, ctx.baseline) if ctx.baseline else ""
            return checker.check(candidate, baseline)
        except Exception as exc:
            return EvalResult(
                score=0.0,
                metric="hard",
                hard_failures=("eval_exception",),
                evidence=(EvalEvidence("programmatic_rule", "eval_bridge", False, False, str(exc)),),
                confidence=0.0,
                recommendation="reject",
            )


def build_default_registry() -> EvalRegistry:
    return EvalRegistry(ResponseContractChecker(ContractCompiler()))


__all__ = ["EvalRegistry", "RegistryEvalBridge", "build_default_registry"]
