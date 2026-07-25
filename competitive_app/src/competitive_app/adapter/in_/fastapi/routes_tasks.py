"""A-group routes — Research tasks (8 routes, placeholder).

PLACEHOLDER — research workflow is NOT frozen (Roadmap §0 / feature F-A14).
Routes only call TaskService; they do not touch pi_agent / aiosqlite (contract G2).
``/report`` returns a stub; ``/sessions`` returns an empty list (feature F-A17).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

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
        competitor_discovery=body.competitor_discovery,
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


__all__ = ["router"]
