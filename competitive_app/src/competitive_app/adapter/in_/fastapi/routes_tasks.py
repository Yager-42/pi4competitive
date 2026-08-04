"""A-group routes — Research tasks (8 routes, placeholder).

PLACEHOLDER — research workflow is NOT frozen (Roadmap §0 / feature F-A14).
Routes only call TaskService; they do not touch pi_agent / aiosqlite (contract G2).
``/report`` returns a stub; ``/sessions`` returns an empty list (feature F-A17).
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from ....application.workflow.task_service import (
    TaskConflictError,
    TaskInputError,
    TaskNotFoundError,
)
from .dto import ClarifyRequest, WorkflowTaskRequest

router = APIRouter(prefix="/api/v2", tags=["tasks"])


def _state(request: Request):
    from .app import get_state

    return get_state(request.app)


@router.post("/tasks", status_code=status.HTTP_202_ACCEPTED)
async def create_task(body: WorkflowTaskRequest, request: Request) -> dict:
    state = _state(request)
    try:
        return await state.task_service.create_task(
            research_brief=body.research_brief,
            query=body.query,
            metadata=body.metadata,
        )
    except TaskInputError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post("/tasks/{task_id}/clarify", status_code=status.HTTP_202_ACCEPTED)
async def submit_clarify(task_id: str, body: ClarifyRequest, request: Request) -> dict:
    """v0.3.3: submit clarify answers → derive brief → start research."""
    state = _state(request)
    try:
        return await state.task_service.submit_clarify(
            task_id, [a.model_dump() for a in body.answers]
        )
    except TaskNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"task not found: {exc}"
        ) from exc
    except TaskConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/tasks")
async def list_tasks(request: Request) -> dict:
    state = _state(request)
    return await state.task_service.list_tasks()


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, request: Request) -> dict:
    state = _state(request)
    try:
        return await state.task_service.get_task(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"task not found: {exc}") from exc


@router.post("/tasks/{task_id}/resume", status_code=status.HTTP_202_ACCEPTED)
async def resume_task(task_id: str, request: Request) -> dict:
    state = _state(request)
    try:
        return await state.task_service.resume_task(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"task not found: {exc}") from exc
    except TaskConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/abort")
async def abort_task(task_id: str, request: Request) -> dict:
    state = _state(request)
    try:
        return await state.task_service.abort_task(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"task not found: {exc}") from exc


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: str, request: Request) -> None:
    state = _state(request)
    try:
        await state.task_service.delete_task(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"task not found: {exc}") from exc
    except TaskConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/tasks/{task_id}/report")
async def get_report(task_id: str, request: Request) -> dict:
    state = _state(request)
    try:
        return await state.task_service.get_report(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"task not found: {exc}") from exc


@router.get("/tasks/{task_id}/sessions")
async def get_task_sessions(task_id: str, request: Request) -> dict:
    state = _state(request)
    try:
        return await state.task_service.get_task_sessions(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"task not found: {exc}") from exc


# ----------------------------------------------------------- v0.3.1 SSE stream


def _sse(event_type: str, data: dict) -> str:
    """Serialize one SSE event frame: `event: <type>\ndata: <json>\n\n`."""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

_SSE_FANOUTS: dict[tuple[int, str], "_QueueFanout"] = {}
# Serializes fanout registration/teardown so a closed fanout is never
# resurrected by a client that subscribed during the cleanup window.
_FANOUT_LOCK = asyncio.Lock()

class _QueueFanout:
    """Broadcast one task queue to independent SSE subscribers."""

    def __init__(self, source: asyncio.Queue[dict]) -> None:
        self._source = source
        self._subscribers: set[asyncio.Queue[dict]] = set()
        self._pump_task: asyncio.Task[None] | None = None
        self._terminal: dict | None = None
        self._closed = False

    @property
    def source(self) -> asyncio.Queue[dict]:
        return self._source

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def idle(self) -> bool:
        return not self._subscribers

    def start(self) -> None:
        if self._pump_task is None and not self._closed:
            self._pump_task = asyncio.create_task(self._pump())

    async def subscribe(self) -> asyncio.Queue[dict]:
        if self._closed:
            raise RuntimeError("fanout is closed")
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        if self._terminal is not None:
            queue.put_nowait(self._terminal)
        elif self._pump_task is None and not self._closed:
            self.start()
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[dict]) -> None:
        # Detach only; the pump stays alive for remaining subscribers and the
        # fanout is closed by close() once it is idle and unregistered.
        self._subscribers.discard(queue)

    async def close(self) -> None:
        """Stop the pump; only the last idle owner may call this."""
        self._closed = True
        task = self._pump_task
        self._pump_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    @staticmethod
    def _enqueue(queue: asyncio.Queue[dict], event: dict) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(event)

    async def _pump(self) -> None:
        try:
            while True:
                event = await self._source.get()
                if event.get("type") in {"done", "error"}:
                    self._terminal = event
                for queue in tuple(self._subscribers):
                    self._enqueue(queue, event)
                if self._terminal is not None:
                    return
        finally:
            self._pump_task = None


async def _subscribe_stream(registry, task_id: str) -> asyncio.Queue[dict] | None:
    """Return a client queue, waiting callers never consume one another's events."""
    async with _FANOUT_LOCK:
        key = (id(registry), task_id)
        fanout = _SSE_FANOUTS.get(key)
        if fanout is None or fanout.closed:
            # Replace a stale closed fanout in-place while holding the lock;
            # never recurse while the non-reentrant asyncio.Lock is held.
            if fanout is not None:
                _SSE_FANOUTS.pop(key, None)
            source = registry.get_stream(task_id)
            if source is None:
                return None
            fanout = _QueueFanout(source)
            _SSE_FANOUTS[key] = fanout
            fanout.start()
        return await fanout.subscribe()


async def _build_snapshot(state, task_id: str) -> dict:
    """state_snapshot event: current projection + SOCM (iteration/evidence_count)."""
    task = await state.store.get_task(task_id)
    proj = (task or {}).get("projection") or {}
    snapshot = {
        "task_id": task_id,
        "status": (task or {}).get("status", "unknown"),
        "current_stage": proj.get("current_stage"),
        "stages": proj.get("stages", {}),
        "coverage": proj.get("coverage", {}),
        "iteration": 0,
        "evidence_count": proj.get("evidence_count", 0),
    }
    session_id = (task or {}).get("session_id")
    if session_id and state.socm_store is not None:
        socm = await state.socm_store.load(session_id)
        snapshot["iteration"] = socm.iteration
        snapshot["evidence_count"] = socm.evidence_graph.node_count()
    return snapshot


@router.get("/tasks/{task_id}/stream")
async def stream_task(task_id: str, request: Request):
    """SSE stream of a task's business events (v0.3.1).

    Pushes a state_snapshot on connect, then live events from the runner/engine
    until done/error or client disconnect. Already-terminal tasks push snapshot
    + terminal event then close. 15s heartbeat keeps proxies alive.
    """
    state = _state(request)
    task = await state.store.get_task(task_id)
    if task is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"task not found: {task_id}"
        )
    task_status = task["status"]

    async def event_gen():
        key = (id(state.registry), task_id)
        q: asyncio.Queue[dict] | None = None
        fanout: _QueueFanout | None = None
        # Snapshot errors are explicit infrastructure events; never report a
        # fabricated task-level failure or mutate persisted task status.
        try:
            try:
                yield _sse("state_snapshot", await _build_snapshot(state, task_id))
            except Exception:  # noqa: BLE001
                yield _sse(
                    "error",
                    {
                        "task_id": task_id,
                        "status": task_status,
                        "code": "snapshot_unavailable",
                        "error_kind": "infrastructure",
                    },
                )
                return
            if task_status in {"completed", "failed", "aborted"}:
                if task_status == "completed":
                    yield _sse("done", {"task_id": task_id, "status": "completed"})
                else:
                    yield _sse("error", {"task_id": task_id, "status": task_status})
                return
            # Each client receives its own queue. If completion wins the lookup
            # race, observe the terminal state from the store instead.
            q = await _subscribe_stream(state.registry, task_id)
            fanout = _SSE_FANOUTS.get(key)
            while q is None and not await request.is_disconnected():
                current = await state.store.get_task(task_id)
                current_status = (current or {}).get("status")
                if current_status in {"completed", "failed", "aborted"}:
                    if current_status == "completed":
                        yield _sse("done", {"task_id": task_id, "status": "completed"})
                    else:
                        yield _sse("error", {"task_id": task_id, "status": current_status})
                    return
                await asyncio.sleep(0.05)
                q = await _subscribe_stream(state.registry, task_id)
                fanout = _SSE_FANOUTS.get(key)
            if q is None:
                return
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                yield _sse(event["type"], event["data"])
                if event["type"] in {"done", "error"}:
                    break
        finally:
            if q is not None and fanout is not None:
                async with _FANOUT_LOCK:
                    await fanout.unsubscribe(q)
                    if fanout.idle:
                        if _SSE_FANOUTS.get(key) is fanout:
                            _SSE_FANOUTS.pop(key, None)
                        await fanout.close()
                        unsubscribe = getattr(state.registry, "unsubscribe_stream", None)
                        if unsubscribe is not None:
                            unsubscribe(task_id, fanout.source)
    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/tasks/{task_id}/trace")
async def get_task_trace(task_id: str, request: Request) -> dict:
    """v0.3.2: call-level trace spans (token/latency per LLM call)."""
    state = _state(request)
    try:
        return await state.task_service.get_trace(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"task not found: {exc}"
        ) from exc


__all__ = ["router"]
