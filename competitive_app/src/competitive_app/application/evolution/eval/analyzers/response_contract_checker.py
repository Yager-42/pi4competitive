"""ResponseContractChecker copied/adapted from Poirot.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/eval/analyzers/response_contract_checker.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: local async application imports; checker itself remains pure and
never adds workflow-specific hard gates.
"""
from __future__ import annotations

from .....domain.evolution.evolution_types import EvalEvidence, EvalResult
from . import checks
from .contract_compiler import ContractCompiler


class ResponseContractChecker:
    def __init__(self, compiler: ContractCompiler | None = None) -> None:
        self._compiler = compiler or ContractCompiler()

    def check(self, candidate_content: str, baseline_content: str = "") -> EvalResult:
        rules = self._compiler.compile(candidate_content)
        evidence: list[EvalEvidence] = []
        hard_failures: list[str] = []
        passed = 0
        for rule in rules:
            candidate_pass = self._run_rule(rule.rule_id, candidate_content, rule.params)
            baseline_pass = self._run_rule(rule.rule_id, baseline_content, rule.params) if baseline_content else True
            passed += int(candidate_pass)
            if rule.hard and not candidate_pass:
                hard_failures.append(rule.rule_id)
            evidence.append(EvalEvidence("programmatic_rule", rule.rule_id, baseline_pass, candidate_pass))
        score = passed / len(rules) if rules else 0.0
        return EvalResult(score, "hard", tuple(hard_failures), tuple(evidence), 0.7,
                          "reject" if hard_failures else "accept")

    @staticmethod
    def _run_rule(rule_id: str, content: str, params: dict) -> bool:
        if rule_id == "nonempty":
            return checks.check_nonempty(content)
        if rule_id == "json_parseable":
            return checks.check_json_parseable(content)
        if rule_id == "must_cite":
            return checks.check_must_cite(content)
        if rule_id == "lead_with_conclusion":
            return checks.check_lead_with_conclusion(content)
        if rule_id == "paragraph_limit":
            return checks.check_paragraph_limit(content, int(params.get("max", checks.PARAGRAPH_LIMIT)))
        if rule_id == "no_unfounded_claims":
            return checks.check_no_unfounded_claims(content)
        if rule_id == "semantic_density":
            density = checks.semantic_density(content)
            return checks.SEMANTIC_DENSITY_MIN <= density <= checks.SEMANTIC_DENSITY_MAX
        return True


__all__ = ["ResponseContractChecker"]
