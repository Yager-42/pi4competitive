"""Scoped Skill selector adapted from Poirot ``skill/selector.py``.
Upstream SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: async App store/Pi LLM, four-scope filtering and task-pinned selection.
"""
from __future__ import annotations
import inspect
import json
import logging
from typing import Any
from ...domain.evolution.skill_types import SkillRecord
from ...domain.evolution.workflow_scope import SkillScope
_log = logging.getLogger(__name__)

async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value

class SkillSelector:
    def __init__(self, store: Any, llm: Any | None = None, max_skills: int = 3,
                 quality_threshold: float = 0.3, min_selections: int = 5) -> None:
        self._store = store; self._llm = llm
        self._max_skills = min(max(0, int(max_skills)), 3)
        self._quality_threshold = quality_threshold; self._min_selections = min_selections

    async def select_for_scope(self, task_description: str, scope: SkillScope,
                               overrides: list[str] | None = None) -> list[SkillRecord]:
        if self._store is None or self._max_skills == 0: return []
        forced: list[SkillRecord] = []
        for name in overrides or []:
            record = await self._store_get_active(name, scope)
            if record is not None and record.enabled and record.skill_id not in {r.skill_id for r in forced}:
                forced.append(record)
                if len(forced) >= self._max_skills:
                    break
        active = await self._store_list_active(scope)
        seen = {r.skill_id for r in forced}
        optional: list[SkillRecord] = []
        for record in self._quality_filter([r for r in active if r.enabled]):
            if record.skill_id not in seen:
                optional.append(record); seen.add(record.skill_id)
        slots = self._max_skills - len(forced)
        if slots <= 0:
            return forced
        if len(optional) <= slots:
            return forced + optional
        selected = await self._llm_select(optional, task_description, slots) if self._llm else []
        return forced + (selected or sorted(optional, key=lambda r: r.effective_rate, reverse=True)[:slots])

    async def select_for_task(self, task_description: str, scope: SkillScope | list[str] = "plan",
                              overrides: list[str] | None = None) -> list[SkillRecord]:
        if isinstance(scope, list): overrides, scope = scope, "plan"
        return await self.select_for_scope(task_description, scope, overrides)

    async def _store_list_active(self, scope: SkillScope) -> list[SkillRecord]:
        supports_scope = True
        try:
            value = self._store.list_active(scope=scope)
        except TypeError:
            supports_scope = False
            value = self._store.list_active()
        records = list(await _await(value) or [])
        # A scoped store is authoritative.  For legacy unscoped stores, fail
        # closed when no scope metadata is available rather than cross-injecting.
        if supports_scope:
            return records
        get_scope = getattr(self._store, "get_scope", None)
        result = []
        for record in records:
            record_scope = await _await(get_scope(record.skill_id)) if get_scope else getattr(record, "scope", None)
            if record_scope == scope:
                result.append(record)
        return result

    async def _store_get_active(self, name: str, scope: SkillScope) -> SkillRecord | None:
        try:
            record = await _await(self._store.get_active(name, scope=scope))
            scoped_query = True
        except TypeError:
            record = await _await(self._store.get_active(name))
            scoped_query = False
        if record is None: return None
        if scoped_query:
            return record
        get_scope = getattr(self._store, "get_scope", None)
        record_scope = await _await(get_scope(record.skill_id)) if get_scope else getattr(record, "scope", None)
        return record if record_scope == scope else None

    def _quality_filter(self, skills: list[SkillRecord]) -> list[SkillRecord]:
        return [r for r in skills if not (r.total_selections >= self._min_selections and r.effective_rate < self._quality_threshold)]

    async def _llm_select(self, candidates: list[SkillRecord], task: str, maximum: int) -> list[SkillRecord]:
        catalog = "\n".join(f"- {r.skill_id}: {r.description} ({r.effective_rate:.0%})" for r in candidates)
        prompt = f"Task: {task}\nAvailable Skills:\n{catalog}\nSelect at most {maximum}; JSON {{\"skills\":[\"skill_id\"]}}"
        try:
            if hasattr(self._llm, "complete_json"): data = await _await(self._llm.complete_json(prompt))
            elif hasattr(self._llm, "complete_simple"): data = await _await(self._llm.complete_simple(prompt))
            else: data = await _await(self._llm.invoke(prompt))
            data = getattr(data, "content", data)
            if isinstance(data, str):
                start, end = data.find("{"), data.rfind("}"); data = json.loads(data[start:end + 1]) if start >= 0 and end > start else {}
            ids = data.get("skills", []) if isinstance(data, dict) else []
            by_id = {r.skill_id: r for r in candidates}
            return [by_id[sid] for sid in ids if sid in by_id][:maximum]
        except Exception as exc:
            _log.warning("Skill selection failed: %s", exc); return []

__all__ = ["SkillSelector"]
