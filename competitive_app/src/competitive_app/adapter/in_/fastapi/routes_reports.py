"""Reports routes — GET /reports + GET /reports/{task_id} (v0.3.1).

Report list (cards) + structured full report. report_id reuses task_id (1:1
task↔report). Routes only call TaskService; no pi_agent / aiosqlite (contract G2).
"""
from __future__ import annotations
import ipaddress

from fastapi import APIRouter, Depends, HTTPException, Request

from ....application.workflow.task_service import TaskNotFoundError
from .dto import FeedbackRequest, RefineRequest

def _require_trusted_local(request: Request) -> None:
    """Reports are single-tenant and intentionally local-only.

    Until a tenant identity contract exists, fail closed for non-loopback
    clients rather than exposing another task's report over a reachable bind.
    Test ASGI callers use the normal loopback client address.
    """
    client = request.client
    if client is None:
        raise HTTPException(status_code=403, detail="reports require a trusted local request")
    try:
        is_loopback = ipaddress.ip_address(client.host).is_loopback
    except ValueError:
        is_loopback = client.host == "localhost"
    if not is_loopback:
        raise HTTPException(status_code=403, detail="reports require a trusted local request")


router = APIRouter(
    prefix="/api/v2",
    tags=["reports"],
    dependencies=[Depends(_require_trusted_local)],
)


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


@router.post("/reports/{task_id}/refine")
async def refine_report(task_id: str, body: RefineRequest, request: Request) -> dict:
    """v0.3.2: rewrite one report section via LLM (append refine stage_output)."""
    try:
        return await _state(request).task_service.refine_report(
            task_id, body.section_id, body.annotations
        )
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"report not found: {exc}") from exc


@router.post("/reports/{task_id}/feedback")
async def post_feedback(task_id: str, body: FeedbackRequest, request: Request) -> dict:
    """v0.3.2: record report revision rate (edited/total blocks)."""
    try:
        return await _state(request).task_service.add_feedback(
            task_id, body.edited_blocks, body.total_blocks, body.data
        )
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"report not found: {exc}") from exc
