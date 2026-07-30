"""ContractCompiler copied from Poirot EvalCompiler.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/eval/analyzers/contract_compiler.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: local domain eval types import; no workflow hard gate or benchmark.
"""
from __future__ import annotations

import re

from .....domain.evolution.eval_types import ContractRule

_RE_PARAGRAPH_LIMIT = re.compile(r"(不超过|少于|最多|within|less than|at most)\s*(\d+)\s*(段|paragraph)", re.IGNORECASE)


class ContractCompiler:
    def compile(self, skill_content: str) -> list[ContractRule]:
        rules = [
            ContractRule("nonempty", "programmatic", True, "SKILL.md body 非空"),
            ContractRule("json_parseable", "programmatic", True, "frontmatter YAML 可解析"),
        ]
        corpus = skill_content.lower()
        if self._mentions_sources(corpus):
            rules.append(ContractRule("must_cite", "programmatic", False, "skill 声明引用来源"))
        if self._mentions_conclusion_first(corpus):
            rules.append(ContractRule("lead_with_conclusion", "programmatic", False, "skill 声明先给结论"))
        maximum = self._paragraph_limit(corpus)
        if maximum:
            rules.append(ContractRule("paragraph_limit", "programmatic", False, "段落限制", {"max": maximum}))
        rules.extend([
            ContractRule("no_unfounded_claims", "programmatic", False, "无绝对化无据声明"),
            ContractRule("semantic_density", "programmatic", False, "指令性词密度"),
        ])
        return rules

    @staticmethod
    def _mentions_sources(corpus: str) -> bool:
        return any(k in corpus for k in ("引用来源", "标注来源", "注明来源", "cite sources", "with sources", "provide sources", "source-backed"))

    @staticmethod
    def _mentions_conclusion_first(corpus: str) -> bool:
        return any(k in corpus for k in ("先给结论", "结论在前", "先说结论", "answer first", "lead with the conclusion", "bottom line first"))

    @staticmethod
    def _paragraph_limit(corpus: str) -> int:
        for match in _RE_PARAGRAPH_LIMIT.finditer(corpus):
            try:
                return max(1, int(match.group(2)))
            except (TypeError, ValueError):
                pass
        return 0


__all__ = ["ContractCompiler"]
