"""Runtime registry — caches AgentHarness instances, locks, and task runners.

Feature F-A10/F-A11:
  - Harnesses cached by session_id so prompts retain Session and extension checkpoints.
  - per-session asyncio.Lock serializes prompts; queue timeout → 409.
  - abort: cancel the in-flight prompt AND all queued waiters (cancelled → 409).
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class _ActiveTask:
    runner: Any
    task: asyncio.Task[Any]


@dataclass(slots=True)
class _TaskStream:
    """Buffered fan-out stream for independent SSE subscribers."""

    history: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=256))
    subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.subscribers.add(queue)
        for event in self.history:
            queue.put_nowait(event)
        return queue

    def publish(self, event: dict[str, Any]) -> None:
        self.history.append(event)
        for queue in tuple(self.subscribers):
            queue.put_nowait(event)


class RuntimeRegistry:
    """Tracks live harnesses (per session) and workflow tasks (per task_id)."""

    def __init__(self) -> None:
        self._harnesses: dict[str, Any] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        # session_id → list of queued prompt waiters (for abort to cancel)
        self._queued: dict[str, list[asyncio.Task[Any]]] = {}
        # task_id → active workflow runner
        self._tasks: dict[str, _ActiveTask] = {}
        # task_id → buffered fan-out stream. Kept after completion so a client
        # racing task completion can still subscribe to the terminal event.
        self._streams: dict[str, _TaskStream] = {}

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
            if not completed.cancelled():
                # Surface exceptions so asyncio doesn't warn; callers handle via DB.
                completed.exception()

        task.add_done_callback(_forget)
        return task

    # --------------------------------------------------- v0.3.1 SSE streams

    def register_stream(self, task_id: str) -> asyncio.Queue[dict[str, Any]]:
        """Pre-register a buffered fan-out stream before runner startup."""
        stream = _TaskStream()
        self._streams[task_id] = stream
        return stream.subscribe()

    def get_stream(self, task_id: str) -> asyncio.Queue[dict[str, Any]] | None:
        stream = self._streams.get(task_id)
        return stream.subscribe() if stream is not None else None

    def publish_stream(self, task_id: str, event: dict[str, Any]) -> None:
        stream = self._streams.get(task_id)
        if stream is not None:
            stream.publish(event)

    def unregister_stream(self, task_id: str) -> None:
        self._streams.pop(task_id, None)


    async def abort_task(self, task_id: str, reason: str = "api_abort") -> bool:
        active = self._tasks.get(task_id)
        if active is None or active.task.done():
            return False
        # The cancellation message preserves the caller's reason for runner
        # diagnostics while retaining the existing cancellation contract.
        active.task.cancel(reason)
        try:
            await active.task
        except asyncio.CancelledError:
            pass
        return True

    # ---------------------------------------------------------------- shutdown

    async def shutdown(self) -> None:
        for item in list(self._tasks.values()):
            item.task.cancel("shutdown")
        if self._tasks:
            await asyncio.gather(
                *(item.task for item in self._tasks.values()), return_exceptions=True
            )
        self._tasks.clear()

        async def _close(harness: Any) -> None:
            try:
                harness.agent.abort()
            except Exception:
                pass
            try:
                await harness.shutdown()
            except Exception:
                pass

        try:
            await asyncio.gather(
                *(_close(h) for h in self._harnesses.values()), return_exceptions=True
            )
        finally:
            self._harnesses.clear()
            self._locks.clear()
            self._queued.clear()
            self._streams.clear()


__all__ = ["RuntimeRegistry"]
