"""Workflow evidence adapter (NEW-HOST).

Reads existing JSONL/SOCM/span/feedback references and builds ordinary
FailureEvidence/context. It does not sanitize, classify, quarantine, or add a
benchmark corpus; feedback cannot directly set mutation fields.
"""
from __future__ import annotations

import json
from typing import Any

from ....domain.evolution.evolution_types import FailureEvidence


class WorkflowEvidenceAdapter:
    def __init__(self, *, store: Any, socm_store: Any = None, repo: Any = None) -> None:
        self._store = store
        self._socm_store = socm_store
        self._repo = repo

    async def collect(self, task_id: str, session_id: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {"task_id": task_id, "spans": [], "feedback": None, "socm": None, "messages": ""}
        try:
            result["spans"] = await self._store.list_spans(task_id)
        except Exception:
            pass
        try:
            result["feedback"] = await self._store.get_feedback(task_id)
        except Exception:
            pass
        if self._socm_store is not None and session_id:
            try:
                result["socm"] = await self._socm_store.load(session_id)
            except Exception:
                pass
        return result

    async def failure_evidence(self, task_id: str, session_id: str | None = None) -> tuple[FailureEvidence, ...]:
        data = await self.collect(task_id, session_id)
        failures: list[FailureEvidence] = []
        for span in data.get("spans", []):
            kind = str(span.get("kind", ""))
            if kind in {"error", "failed", "fallback"}:
                failures.append(FailureEvidence(span.get("seq"), span.get("entity"), "IMPLEMENTATION", json.dumps(span, ensure_ascii=False)))
        feedback = data.get("feedback") or {}
        if feedback and feedback.get("revision_rate", 0) > 0:
            failures.append(FailureEvidence(None, "feedback", "IMPLEMENTATION", "ordinary report feedback indicates revision"))
        return tuple(failures)


__all__ = ["WorkflowEvidenceAdapter"]
