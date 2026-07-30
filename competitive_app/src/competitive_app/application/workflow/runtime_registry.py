"""Runtime registry — caches AgentHarness instances, locks, and task runners.

Feature F-A10/F-A11:
  - Harnesses cached by session_id so prompts retain Session and extension checkpoints.
  - per-session asyncio.Lock serializes prompts; queue timeout → 409.
  - abort: cancel the in-flight prompt AND all queued waiters (cancelled → 409).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class _ActiveTask:
    runner: Any
    task: asyncio.Task[Any]


class RuntimeRegistry:
    """Tracks live harnesses (per session) and workflow tasks (per task_id)."""

    def __init__(self) -> None:
        self._harnesses: dict[str, Any] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        # session_id → list of queued prompt waiters (for abort to cancel)
        self._queued: dict[str, list[asyncio.Task[Any]]] = {}
        # task_id → active workflow runner
        self._tasks: dict[str, _ActiveTask] = {}
        # v0.3.1 SSE: task_id → event queue (pre-registered on create_task so
        # an early SSE connection doesn't miss events before the runner emits).
        self._streams: dict[str, asyncio.Queue[Any]] = {}

    # ---------------------------------------------------------------- harnesses

    def register_harness(self, session_id: str, harness: Any) -> Any:
        existing = self._harnesses.get(session_id)
        if existing is None:
            self._harnesses[session_id] = harness
            return harness
        return existing

    def get_harness(self, session_id: str) -> Any | None:
        return self._harnesses.get(session_id)

    def get_agent(self, session_id: str) -> Any | None:
        harness = self.get_harness(session_id)
        return harness.agent if harness is not None else None

    def drop_harness(self, session_id: str) -> None:
        self._harnesses.pop(session_id, None)
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
        harness = self._harnesses.get(session_id)
        aborted_in_flight = False
        if harness is not None:
            agent = harness.agent
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
            # v0.3.1 SSE: drop the event queue once the task is done. SSE clients
            # that reconnect after completion read the terminal state from the
            # store (state_snapshot), not from this queue.
            self._streams.pop(task_id, None)
            if not completed.cancelled():
                # Surface exceptions so asyncio doesn't warn; callers handle via DB.
                completed.exception()

        task.add_done_callback(_forget)
        return task

    # --------------------------------------------------- v0.3.1 SSE streams

    def register_stream(self, task_id: str) -> asyncio.Queue[Any]:
        """Pre-register an event queue for a task (before the runner emits).

        Called by task_service on create_task/resume_task so an SSE client
        connecting during pending→running doesn't miss early events.
        """
        q: asyncio.Queue[Any] = asyncio.Queue()
        self._streams[task_id] = q
        return q

    def get_stream(self, task_id: str) -> asyncio.Queue[Any] | None:
        return self._streams.get(task_id)

    def unregister_stream(self, task_id: str) -> None:
        self._streams.pop(task_id, None)

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
        for harness in self._harnesses.values():
            harness.agent.abort()
            await harness.shutdown()
        self._harnesses.clear()
        self._locks.clear()
        self._queued.clear()
        self._streams.clear()


__all__ = ["RuntimeRegistry"]
