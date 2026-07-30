"""Selection/outcome/provenance metrics host adapter.

Selection is recorded by ``SkillVersionSnapshot`` at first binding. Terminal
outcomes are recorded only for completed/failed tasks; aborted tasks are ignored.
"""
from __future__ import annotations

from typing import Any

from ...domain.evolution.eval_types import SkillJudgment


class SkillMetricsRecorder:
    def __init__(self, skill_store: Any) -> None:
        self._store = skill_store

    async def record_outcome(
        self,
        *,
        task_id: str,
        status: str,
        judgments: list[SkillJudgment] | None = None,
        applied_by_skill: dict[str, bool | None] | None = None,
        note: str = "",
    ) -> None:
        if status not in {"completed", "failed"}:
            return
        values = applied_by_skill or {
            judgment.skill_id: judgment.skill_applied for judgment in judgments or []
        }
        for skill_id, applied in values.items():
            await self._store.record_outcome(skill_id, task_id, applied, status == "completed", note)

    async def record_judgments(self, judgments: list[SkillJudgment], task_completed: bool) -> None:
        for judgment in judgments:
            await self._store.save_judgment(judgment)
            await self._store.record_outcome(
                judgment.skill_id, judgment.task_id, judgment.skill_applied, task_completed, judgment.deviation_note
            )


__all__ = ["SkillMetricsRecorder"]
