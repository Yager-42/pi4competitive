"""Reports routes — GET /reports + GET /reports/{task_id} (v0.3.1).

Report list (cards) + structured full report. report_id reuses task_id (1:1
task↔report). Routes only call TaskService; no pi_agent / aiosqlite (contract G2).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ....application.workflow.task_service import TaskNotFoundError

router = APIRouter(prefix="/api/v2", tags=["reports"])


def _state(request: Request):
    from .app import get_state

    return get_state(request.app)


@router.get("/reports")
async def list_reports(request: Request) -> dict:
    """List completed-task report cards (newest first)."""
    return await _state(request).task_service.list_reports()


@router.get("/reports/{task_id}")
async def get_report(task_id: str, request: Request) -> dict:
    """Structured full report (real-time assembly from JSONL + SOCM)."""
    try:
        return await _state(request).task_service.get_report_full(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"report not found: {exc}") from exc
