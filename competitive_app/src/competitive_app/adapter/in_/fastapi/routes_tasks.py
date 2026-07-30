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

from ....application.workflow.task_service import TaskConflictError, TaskNotFoundError
from .dto import WorkflowTaskRequest

router = APIRouter(prefix="/api/v2", tags=["tasks"])


def _state(request: Request):
    from .app import get_state

    return get_state(request.app)


@router.post("/tasks", status_code=status.HTTP_202_ACCEPTED)
async def create_task(body: WorkflowTaskRequest, request: Request) -> dict:
    state = _state(request)
    return await state.task_service.create_task(
        research_brief=body.research_brief,
        metadata=body.metadata,
    )


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
        try:
            socm = await state.socm_store.load(session_id)
            snapshot["iteration"] = socm.iteration
            snapshot["evidence_count"] = socm.evidence_graph.node_count()
        except Exception:  # noqa: BLE001
            pass  # keep projection defaults
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
        # 1. Always push a snapshot first (covers running/pending/terminal).
        yield _sse("state_snapshot", await _build_snapshot(state, task_id))
        # 2. Terminal: push terminal event + close.
        if task_status in {"completed", "failed", "aborted"}:
            if task_status == "completed":
                yield _sse("done", {"task_id": task_id, "status": "completed"})
            else:
                yield _sse("error", {"task_id": task_id, "status": task_status})
            return
        # 3. Running/pending: consume the pre-registered queue until terminal.
        q = state.registry.get_stream(task_id)
        while not await request.is_disconnected():
            try:
                event = await asyncio.wait_for(q.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"  # keep-alive (SSE comment, client ignores)
                continue
            yield _sse(event["type"], event["data"])
            if event["type"] in {"done", "error"}:
                break

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router"]
