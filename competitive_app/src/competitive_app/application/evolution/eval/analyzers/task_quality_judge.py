"""TaskQualityJudge adapted from Poirot post-execution judge.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/eval/analyzers/task_quality_judge.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: Pi async adapter and app store; caps/weights are unchanged and the
score is not used by promotion gates.
"""
from __future__ import annotations

import inspect
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .....domain.evolution.eval_types import TaskQualityScore

_WEIGHTS = {"task_completion": 0.50, "response_quality": 0.35, "efficiency": 0.05, "tool_usage": 0.10}
_MAX_TRACE_CHARS = 80000
_MAX_OUTPUT_CHARS = 20000


async def _invoke(llm: Any, prompt: str) -> Any:
    method = getattr(llm, "complete_json", None) or getattr(llm, "complete_simple", None) or getattr(llm, "invoke", None)
    if method is None:
        raise TypeError("unsupported LLM adapter")
    result = method(prompt)
    if inspect.isawaitable(result):
        result = await result
    return getattr(result, "content", result)


class TaskQualityJudge:
    def __init__(self, llm: Any | None = None, store: Any = None) -> None:
        self._llm = llm
        self._store = store

    async def judge_task(self, task_id: str, execution_trace: str, final_output: str) -> TaskQualityScore | None:
        if self._llm is None:
            return None
        try:
            trace = (execution_trace or "")[:_MAX_TRACE_CHARS]
            output = (final_output or "")[:_MAX_OUTPUT_CHARS]
            raw = await _invoke(self._llm, (
                "Evaluate workflow task quality from 0 to 1. Return only JSON with "
                "task_completion,response_quality,efficiency,tool_usage,rationale.\n"
                f"Execution trace:\n{trace}\n\nFinal output:\n{output}"
            ))
            data = raw if isinstance(raw, dict) else self._extract_json(str(raw))
            if not isinstance(data, dict):
                return None
            dims = {key: max(0.0, min(1.0, float(data.get(key, 0.5)))) for key in _WEIGHTS}
            score = TaskQualityScore(
                score_id=f"score_{uuid.uuid4().hex[:12]}", task_id=task_id,
                task_completion=dims["task_completion"], response_quality=dims["response_quality"],
                efficiency=dims["efficiency"], tool_usage=dims["tool_usage"],
                overall_score=round(sum(dims[key] * weight for key, weight in _WEIGHTS.items()), 3),
                rationale=str(data.get("rationale", "")), timestamp=datetime.now(timezone.utc).isoformat(),
            )
            if self._store is not None:
                await self._store.save_task_score(score)
            return score
        except Exception:
            return None

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


__all__ = ["TaskQualityJudge", "_WEIGHTS", "_MAX_TRACE_CHARS", "_MAX_OUTPUT_CHARS"]
