"""ProgrammaticEvalBridge facade copied from Poirot.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/evolution/eval/programmatic_bridge.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: async file boundary via ``asyncio.to_thread``; static check facade
is retained for parity and no benchmark is introduced.
"""
from __future__ import annotations

import asyncio

from ....domain.evolution.evolution_types import EvalContext, EvalResult
from .analyzers import checks
from .analyzers.contract_compiler import ContractCompiler
from .analyzers.response_contract_checker import ResponseContractChecker

_HARD_MODES = checks.HARD_MODES
_DIRECTIVE_WORDS = checks.DIRECTIVE_WORDS
_UNFOUNDED_WORDS = checks.UNFOUNDED_WORDS
_CONCLUSION_WORDS = checks.CONCLUSION_WORDS
_CITE_PATTERN = checks.CITE_PATTERN
_YAML_FRONTMATTER = checks.YAML_FRONTMATTER
_PARAGRAPH_LIMIT = checks.PARAGRAPH_LIMIT
_SEMANTIC_DENSITY_MIN = checks.SEMANTIC_DENSITY_MIN
_SEMANTIC_DENSITY_MAX = checks.SEMANTIC_DENSITY_MAX


class ProgrammaticEvalBridge:
    def __init__(self) -> None:
        self._checker = ResponseContractChecker(ContractCompiler())

    async def evaluate(self, ctx: EvalContext) -> EvalResult:
        candidate = await asyncio.to_thread(self._read_content, ctx.candidate)
        baseline = await asyncio.to_thread(self._read_content, ctx.baseline) if ctx.baseline else ""
        return self._checker.check(candidate, baseline)

    @staticmethod
    def _read_content(record: object | None) -> str:
        return checks.read_content(record) if record is not None else ""

    _split_body = staticmethod(checks.split_body)
    _check_nonempty = staticmethod(checks.check_nonempty)
    _check_json_parseable = staticmethod(checks.check_json_parseable)
    _check_must_cite = staticmethod(checks.check_must_cite)
    _check_paragraph_limit = staticmethod(checks.check_paragraph_limit)
    _check_lead_with_conclusion = staticmethod(checks.check_lead_with_conclusion)
    _check_no_unfounded_claims = staticmethod(checks.check_no_unfounded_claims)
    _semantic_density = staticmethod(checks.semantic_density)


__all__ = ["ProgrammaticEvalBridge"]
