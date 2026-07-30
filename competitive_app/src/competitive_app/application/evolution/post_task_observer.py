"""Post-task observation and evidence-shaped CAPTURED eligibility (NEW-HOST)."""
from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

from ...domain.evolution.evolution_types import EvolutionContext


class PostTaskObserver:
    def __init__(self, *, observation_store: Any, skill_store: Any | None = None) -> None:
        self._observations = observation_store
        self._skills = skill_store

    async def observe(
        self,
        *,
        task_id: str,
        status: str,
        scope: str,
        problem_signature: str,
        solution: str = "",
        transferability: str = "",
        evidence_refs: list[dict[str, Any]] | None = None,
        suggested_name: str = "",
        solution_demonstrated: bool = False,
    ) -> EvolutionContext | None:
        # Aborted tasks are completely ignored.
        if status == "aborted":
            return None
        problem = problem_signature.strip()
        if not problem:
            return None
        refs = evidence_refs or []
        observation_id = f"obs_{uuid.uuid4().hex[:12]}"
        await self._observations.add_observation(
            observation_id=observation_id, task_id=task_id, scope=scope,
            problem_signature=problem, solution=solution, transferability=transferability,
            evidence_refs=refs,
        )
        # Observation-only unless every CAPTURED criterion is present.
        if status not in {"completed", "failed"} or not solution.strip() or not transferability.strip() or not solution_demonstrated:
            return None
        normalized = self._normalize(problem)
        existing = await self._observations.list_observations(scope=scope, unconsumed_only=False)
        if sum(self._normalize(str(item.get("problem_signature", ""))) == normalized for item in existing) > 1:
            return None
        name = suggested_name or f"learned-{hashlib.sha256(normalized.encode()).hexdigest()[:8]}"
        return EvolutionContext(
            trigger="CAPTURE", evolution_type="CAPTURED", target_skill=None,
            capture_pattern=f"Problem: {problem}\nSolution: {solution}\nTransferability: {transferability}",
            suggested_name=self._safe_name(name), scope=scope, observation_id=observation_id,
        )

    async def mark_consumed(self, observation_id: str | None) -> bool:
        if not observation_id or not hasattr(self._observations, "mark_consumed"):
            return False
        return bool(await self._observations.mark_consumed(observation_id))

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(value.lower().split())

    @staticmethod
    def _safe_name(value: str) -> str:
        value = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
        return value[:64] or "learned-skill"


__all__ = ["PostTaskObserver"]
