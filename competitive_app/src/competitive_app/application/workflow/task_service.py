"""Task service — create / list / get / resume / abort / delete (placeholder runner).

PLACEHOLDER — research workflow is NOT frozen (Roadmap §0 / feature F-A14/F-A16).
The placeholder runner does NOT run an agent, does NOT write JSONL, and does NOT
create a session. It flips the SQLite projection status pending→running→completed
and exits. ``session_id`` stays None (feature F-A17: 0:0 in placeholder phase).

When a real workflow feature lands, replace ``_run_placeholder`` with the real
runner; the route layer and this service's public surface stay stable.
"""
from __future__ import annotations

import asyncio
from typing import Any

from ...domain.task import Task, TaskStatusError
from .runtime_registry import RuntimeRegistry


class TaskNotFoundError(Exception):
    """Raised when a task_id is not in the store (→ 404)."""


class TaskConflictError(Exception):
    """Raised when a task is already running (→ 409)."""


class TaskService:
    def __init__(
        self,
        *,
        store: Any,
        repo: Any,
        registry: RuntimeRegistry,
    ) -> None:
        self._store = store
        self._repo = repo
        self._registry = registry

    async def create_task(
        self,
        *,
        research_brief: dict[str, Any],
        competitor_discovery: dict[str, Any],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        import uuid

        task_id = uuid.uuid4().hex
        query = _display_title(research_brief)
        task = Task(
            task_id=task_id,
            query=query,
            status="pending",
            metadata=metadata,
        )
        await self._store.create_task(
            task_id=task_id,
            query=query,
            status="pending",
            metadata=metadata,
            projection=task.to_projection(),
        )
        # Kick off the placeholder runner; POST /tasks always returns pending
        # regardless of how fast the runner finishes (feature F-A16).
        self._registry.start_task(task_id, self, self._run_placeholder(task_id))
        return {
            "task_id": task_id,
            "session_id": None,
            "status": "pending",
            "query": query,
        }

    async def list_tasks(self) -> dict[str, Any]:
        tasks = await self._store.list_tasks()
        return {"tasks": tasks}

    async def get_task(self, task_id: str) -> dict[str, Any]:
        task = await self._store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task

    async def resume_task(self, task_id: str) -> dict[str, Any]:
        task = await self._store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        if task["status"] == "completed":
            return {"task_id": task_id, "status": "completed"}
        if self._registry.task_active(task_id):
            raise TaskConflictError(f"task {task_id} is already running")
        self._registry.start_task(task_id, self, self._run_placeholder(task_id))
        return {"task_id": task_id, "status": "pending"}

    async def abort_task(self, task_id: str) -> dict[str, Any]:
        task = await self._store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        # Boundary case (feature F-A18): terminal tasks are sticky — abort is a
        # no-op on status but still returns aborted.
        await self._registry.abort_task(task_id, "api_abort")
        return {"task_id": task_id, "status": "aborted"}

    async def delete_task(self, task_id: str) -> None:
        task = await self._store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        # If a runner is somehow still active (e.g. placeholder asyncio.Task not
        # yet scheduled to done), cancel it before deleting. The placeholder
        # runner flips status synchronously, so by the time delete runs the DB
        # status is usually already terminal.
        if self._registry.task_active(task_id):
            await self._registry.abort_task(task_id, "delete")
        session_id = await self._store.delete_task(task_id)
        if session_id:
            await self._cascade_delete_session(session_id)

    async def get_report(self, task_id: str) -> dict[str, Any]:
        task = await self._store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        # PLACEHOLDER: report schema not frozen (feature F-A8).
        return {
            "task_id": task_id,
            "status": task["status"],
            "report": None,
            "note": "research workflow not frozen (Roadmap §0)",
        }

    async def get_task_sessions(self, task_id: str) -> dict[str, Any]:
        task = await self._store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        # Placeholder phase: task creates no session (feature F-A17).
        return {"task_id": task_id, "sessions": []}

    # ----------------------------------------------------------- placeholder

    async def _run_placeholder(self, task_id: str) -> None:
        """PLACEHOLDER runner: flip status pending→running→completed, no agent.

        Does NOT write JSONL, does NOT create a session. Replace with the real
        workflow runner when the workflow feature is frozen.
        """
        try:
            await self._store.update_task_status(task_id, "running")
            await self._store.update_task_status(task_id, "completed")
        except Exception:
            await self._store.update_task_status(task_id, "failed")

    async def _cascade_delete_session(self, session_id: str) -> None:
        record = await self._store.get_session(session_id)
        if record is None:
            return
        try:
            await self._repo.delete({"path": record["file_path"], "cwd": record["cwd"]})
        except Exception:
            # Best-effort: JSONL file may already be gone. Still drop the index.
            pass
        await self._store.delete_session(session_id)


def _display_title(research_brief: dict[str, Any]) -> str:
    target = research_brief.get("target") if isinstance(research_brief, dict) else None
    if isinstance(target, dict):
        name = target.get("name") or target.get("category_description")
        if isinstance(name, str) and name.strip():
            return name.strip()[:120]
    goal = research_brief.get("goal") if isinstance(research_brief, dict) else None
    if isinstance(goal, str) and goal.strip():
        return goal.strip()[:120]
    return "research task"


__all__ = ["TaskConflictError", "TaskNotFoundError", "TaskService"]
