"""Task-pinned per-scope Skill version snapshot (NEW-HOST).

Selection is delayed until the stage first enters. Once persisted, all resumes
reuse exactly those IDs; active promotion/rollback never rewrites bindings.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...domain.evolution.skill_types import SkillRecord
from ...domain.evolution.workflow_scope import SkillScope


class SkillVersionSnapshot:
    def __init__(self, *, selector: Any, skill_store: Any, binding_store: Any) -> None:
        self._selector = selector
        self._skill_store = skill_store
        self._binding_store = binding_store

    async def ensure_scope(
        self, task_id: str, scope: SkillScope, task_description: str, overrides: list[str] | None = None
    ) -> list[SkillRecord]:
        bound = await self._binding_store.get_bindings(task_id, scope)
        has_binding = getattr(self._binding_store, "has_binding", None)
        if bound or (has_binding is not None and await has_binding(task_id, scope)):
            return await self._records(bound)
        selected = await self._selector.select_for_scope(task_description, scope, overrides)
        ids = [record.skill_id for record in selected[:3]]
        persisted = await self._binding_store.bind(task_id, scope, ids)
        # Selection is counted only once, at first binding.
        if persisted == ids:
            for skill_id in persisted:
                await self._skill_store.record_selection(skill_id)
        return await self._records(persisted)

    async def get_scope(self, task_id: str, scope: SkillScope) -> list[SkillRecord]:
        return await self._records(await self._binding_store.get_bindings(task_id, scope))

    async def all_bindings(self, task_id: str) -> dict[str, list[SkillRecord]]:
        raw = await self._binding_store.get_bindings(task_id)
        return {scope: await self._records(ids) for scope, ids in raw.items()}

    async def _records(self, ids: list[str]) -> list[SkillRecord]:
        result: list[SkillRecord] = []
        for skill_id in ids:
            record = await self._skill_store.get(skill_id)
            if record is not None:
                result.append(record)
        return result


__all__ = ["SkillVersionSnapshot"]
