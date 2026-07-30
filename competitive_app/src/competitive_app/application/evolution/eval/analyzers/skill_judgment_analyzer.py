"""Async SkillJudgmentAnalyzer adapted from Poirot execution eval.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/eval/analyzers/skill_judgment_analyzer.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: Pi async adapter and App SQLite; JSONL/SOCM summaries are supplied
by the workflow and no middleware/second runtime is introduced.
"""
from __future__ import annotations

import inspect
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .....domain.evolution.eval_types import EvolutionSuggestion, SkillJudgment

_MAX_MESSAGES_CHARS = 80000
_MAX_JOURNAL_EVENTS = 50


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _invoke(llm: Any, prompt: str) -> Any:
    if hasattr(llm, "complete_json"):
        value = llm.complete_json(prompt)
    elif hasattr(llm, "complete_simple"):
        value = llm.complete_simple(prompt)
    elif hasattr(llm, "invoke"):
        value = llm.invoke(prompt)
    elif callable(llm):
        value = llm(prompt)
    else:
        raise TypeError("unsupported LLM adapter")
    value = await value if inspect.isawaitable(value) else value
    return getattr(value, "content", value)


class SkillJudgmentAnalyzer:
    def __init__(self, llm: Any | None = None, store: Any = None) -> None:
        self._llm = llm
        self._store = store

    async def analyze_execution(
        self,
        task_id: str,
        journal_events: list[dict],
        messages_summary: str,
        injected_skills: list[dict],
        task_completed: bool = True,
    ) -> tuple[list[SkillJudgment], list[EvolutionSuggestion]]:
        if not injected_skills or self._llm is None:
            return [], []
        try:
            judgments, suggestions = await self._llm_analyze(task_id, journal_events, messages_summary, injected_skills)
        except Exception:
            return [], []
        if self._store is not None:
            for judgment in judgments:
                try:
                    await self._store.save_judgment(judgment)
                    await self._store.record_outcome(
                        judgment.skill_id, task_id, judgment.skill_applied, task_completed, judgment.deviation_note
                    )
                except Exception:
                    pass
        return judgments, suggestions

    async def _llm_analyze(self, task_id: str, events: list[dict], summary: str, skills: list[dict]):
        skills_text = "\n".join(f"{i + 1}. {s['skill_id']}: {s.get('name', '')} — {s.get('description', '')}" for i, s in enumerate(skills))
        events_text = "\n".join(f"- {e.get('event_type', e.get('type', ''))}: {json.dumps(e, ensure_ascii=False)[:200]}" for e in (events or [])[:_MAX_JOURNAL_EVENTS]) or "(无事件)"
        prompt = (
            "Analyze a completed workflow task. For each injected Skill determine whether its guidance was applied.\n\n"
            f"Injected Skills:\n{skills_text}\n\nExecution summary:\n{(summary or '')[:_MAX_MESSAGES_CHARS]}\n\nEvents:\n{events_text}\n\n"
            'Return only JSON: {"judgments":[{"skill_id":"...","skill_applied":true,"deviation_note":"..."}],'
            '"suggestions":[{"evolution_type":"FIX|DERIVED|CAPTURED","target_skill_ids":["..."],"direction":"..."}]}'
        )
        raw = await _invoke(self._llm, prompt)
        data = raw if isinstance(raw, dict) else self._extract_json(str(raw))
        if not isinstance(data, dict):
            return [], []
        by_id = {s["skill_id"]: s for s in skills}
        by_name = {str(s.get("name", "")): s for s in skills if s.get("name")}
        def resolve_skill(raw_id: object) -> tuple[str, dict] | None:
            key = str(raw_id or "")
            record = by_id.get(key) or by_name.get(key)
            if record is None and key.isdigit():
                index = int(key) - 1
                if 0 <= index < len(skills): record = skills[index]
            return (record["skill_id"], record) if record is not None else None
        judgments = []
        for item in data.get("judgments", []):
            if not isinstance(item, dict): continue
            resolved = resolve_skill(item.get("skill_id") or item.get("name") or item.get("skill"))
            if resolved is None: continue
            skill_id, record = resolved
            judgments.append(SkillJudgment(
                judgment_id=f"judgment_{uuid.uuid4().hex[:12]}", skill_id=skill_id,
                skill_name=record.get("name", ""), task_id=task_id,
                skill_applied=bool(item.get("skill_applied", False)),
                deviation_note=str(item.get("deviation_note", "")), timestamp=_now(),
            ))
        suggestions = []
        for item in data.get("suggestions", []):
            if not isinstance(item, dict):
                continue
            kind = item.get("evolution_type", "FIX")
            if kind not in {"FIX", "DERIVED", "CAPTURED"}:
                kind = "FIX"
            suggestions.append(EvolutionSuggestion(kind, tuple(item.get("target_skill_ids", [])), str(item.get("direction", ""))))
        return judgments, suggestions

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(text[start : end + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None


__all__ = ["SkillJudgmentAnalyzer"]
