"""Async EvolutionManager adapted from Poirot manager.py.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/evolution/manager.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: asyncio boundaries, no manual ``capture_skill`` API, and lifecycle
file projection callback. The trigger→focus→mutate→eval→gate→record ordering
is unchanged; DERIVED never enters this manager.
"""
from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timezone
from typing import Any

from ...domain.evolution.evolution_types import EvalContext, EvolutionContext, EvolutionRecord


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class EvolutionManager:
    def __init__(self, store: Any, triggers: list[Any], focuser: Any, mutator: Any, eval_bridge: Any,
                 gate: Any, llm: Any | None = None, skill_files: Any | None = None, scope_store: Any | None = None) -> None:
        self._store = store
        self._triggers = triggers
        self._focuser = focuser
        self._mutator = mutator
        self._eval_bridge = eval_bridge
        self._gate = gate
        self._llm = llm
        self._skill_files = skill_files
        self._scope_store = scope_store

    async def run_cycle(self) -> list[EvolutionRecord]:
        records: list[EvolutionRecord] = []
        for trigger in self._triggers:
            contexts = await _await(trigger.should_trigger(self._store))
            for context in contexts:
                record = await self.run_context(context)
                if record is not None:
                    records.append(record)
                if context.target_skill is not None and hasattr(trigger, "mark_evolved"):
                    trigger.mark_evolved(context.target_skill.name, context.target_skill.total_selections)
        return records

    async def _rollback_acceptance(self, baseline: Any, candidate: Any) -> None:
        if baseline is not None:
            try:
                await self._store.rollback(baseline.skill_id)
            except Exception:
                pass
        if self._skill_files is not None:
            try:
                await self._skill_files.reject_candidate(candidate)
            except Exception:
                pass
            try:
                await self._skill_files.update_manifest()
            except Exception:
                pass
        clearer = None
        if self._scope_store is not None:
            for name in ("remove_scope", "delete_scope", "clear_scope"):
                candidate_clearer = getattr(self._scope_store, name, None)
                if candidate_clearer is not None:
                    clearer = candidate_clearer
                    break
        if clearer is not None:
            try:
                await _await(clearer(candidate.skill_id))
            except Exception:
                pass

    async def run_context(self, context: EvolutionContext) -> EvolutionRecord | None:
        if context.evolution_type == "DERIVED":
            return None
        focused = await _await(self._focuser.focus(context, self._store))
        candidate, mutation_diff = await _await(self._mutator.mutate(focused, self._llm))
        baseline = focused.target_skill
        metrics = await self._store.get_metrics(baseline.skill_id) if baseline is not None else None
        evaluation = await _await(self._eval_bridge.evaluate(EvalContext(baseline, candidate, metrics)))
        decision = self._gate.decide(candidate, baseline, evaluation)
        created_id: str | None = None
        if decision.recommendation in {"accept", "accept_new_best"}:
            try:
                created_id = await self._store.create_version(
                    baseline.skill_id if baseline else "", candidate, candidate.lineage.origin
                )
                if self._skill_files is not None:
                    await self._skill_files.accept_candidate(candidate, scope=focused.scope)
            except Exception:
                await self._rollback_acceptance(baseline, candidate)
                return None
        record = EvolutionRecord(
            evolution_id=f"evo_{uuid.uuid4().hex[:12]}",
            skill_name=candidate.name,
            evolution_type=focused.evolution_type,
            trigger=focused.trigger,
            baseline_id=baseline.skill_id if baseline else None,
            candidate_id=candidate.skill_id,
            failure_focus=focused.fix_direction or focused.capture_pattern,
            mutation_diff=mutation_diff,
            eval_score=evaluation.score,
            gate_decision=decision.recommendation,
            created_version_id=created_id,
            timestamp=_now(),
        )
        try:
            await self._store.record_evolution(record)
        except Exception:
            # Fail closed: retain candidate files for forensics and restore baseline
            # active pointer if version creation already happened.
            if created_id is not None and baseline is not None:
                try:
                    await self._store.rollback(baseline.skill_id)
                except Exception:
                    pass
            return None
        if decision.recommendation not in {"accept", "accept_new_best"} and self._skill_files is not None:
            await self._skill_files.reject_candidate(candidate)
        return record


__all__ = ["EvolutionManager"]
