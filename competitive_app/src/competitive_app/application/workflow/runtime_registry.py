"""Runtime registry — caches Agent instances + per-session locks + task runners.

Feature F-A10/F-A11:
  - Agents cached by session_id (reuse, avoid re-opening JSONL each prompt).
  - per-session asyncio.Lock serializes prompts; queue timeout → 409.
  - abort: cancel the in-flight prompt AND all queued waiters (cancelled → 409).

Rewritten from legacy ``RuntimeRegistry`` (competitive-agent rr-refactor) — same
shape, different types (uses earendil_works.pi_agent.Agent, not legacy Agent).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from earendil_works.pi_agent.agent import Agent


@dataclass(slots=True)
class _ActiveTask:
    runner: Any
    task: asyncio.Task[Any]


class RuntimeRegistry:
    """Tracks live agents (per session) and workflow tasks (per task_id)."""

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        # session_id → list of queued prompt waiters (for abort to cancel)
        self._queued: dict[str, list[asyncio.Task[Any]]] = {}
        # task_id → active placeholder runner
        self._tasks: dict[str, _ActiveTask] = {}

    # ------------------------------------------------------------------ agents

    def get_or_create_agent(self, session_id: str, factory: Any) -> Agent:
        agent = self._agents.get(session_id)
        if agent is None:
            agent = factory()
            self._agents[session_id] = agent
        return agent

    def get_agent(self, session_id: str) -> Agent | None:
        return self._agents.get(session_id)

    def drop_agent(self, session_id: str) -> None:
        self._agents.pop(session_id, None)
        self._locks.pop(session_id, None)
        for waiter in self._queued.pop(session_id, []):
            waiter.cancel()

    def lock_for(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock

    def register_queued(self, session_id: str, waiter: asyncio.Task[Any]) -> None:
        self._queued.setdefault(session_id, []).append(waiter)

    def unregister_queued(self, session_id: str, waiter: asyncio.Task[Any]) -> None:
        queued = self._queued.get(session_id)
        if queued and waiter in queued:
            queued.remove(waiter)

    async def abort_session(self, session_id: str) -> bool:
        """Abort the in-flight prompt + cancel all queued waiters.

        Returns True if an in-flight agent run was aborted.
        """
        agent = self._agents.get(session_id)
        aborted_in_flight = False
        if agent is not None:
            # Agent.abort() is a no-op if no active run; that's fine.
            agent.abort()
            aborted_in_flight = agent.signal is not None
        for waiter in self._queued.pop(session_id, []):
            waiter.cancel()
        return aborted_in_flight

    # ------------------------------------------------------------------- tasks

    def task_active(self, task_id: str) -> bool:
        item = self._tasks.get(task_id)
        return item is not None and not item.task.done()

    def start_task(self, task_id: str, runner: Any, operation: Any) -> asyncio.Task[Any]:
        if self.task_active(task_id):
            raise RuntimeError("task is already running")
        task = asyncio.create_task(operation, name=f"task:{task_id}")
        self._tasks[task_id] = _ActiveTask(runner=runner, task=task)

        def _forget(completed: asyncio.Task[Any]) -> None:
            current = self._tasks.get(task_id)
            if current is not None and current.task is completed:
                self._tasks.pop(task_id, None)
            if not completed.cancelled():
                # Surface exceptions so asyncio doesn't warn; callers handle via DB.
                completed.exception()

        task.add_done_callback(_forget)
        return task

    async def abort_task(self, task_id: str, reason: str = "api_abort") -> bool:
        active = self._tasks.get(task_id)
        if active is None or active.task.done():
            return False
        active.task.cancel()
        try:
            await active.task
        except (asyncio.CancelledError, Exception):
            pass
        return True

    # ---------------------------------------------------------------- shutdown

    async def shutdown(self) -> None:
        for item in list(self._tasks.values()):
            item.task.cancel()
        if self._tasks:
            await asyncio.gather(
                *(item.task for item in self._tasks.values()), return_exceptions=True
            )
        self._tasks.clear()
        for agent in self._agents.values():
            agent.abort()
        self._agents.clear()
        self._locks.clear()
        self._queued.clear()


__all__ = ["RuntimeRegistry"]
