"""Subscriptions routes — competitive-intelligence monitoring (v0.3.3).

Lightweight alignment with VerdaAI: saved queries + manual re-run + run history.
No in-process scheduler (use external cron for periodic runs). Routes only call
TaskService (contract G2).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from ....application.workflow.task_service import TaskNotFoundError
from .dto import SubscriptionRequest

router = APIRouter(prefix="/api/v2", tags=["subscriptions"])


def _state(request: Request):
    from .app import get_state

    return get_state(request.app)


@router.post("/subscriptions", status_code=status.HTTP_201_CREATED)
async def create_subscription(body: SubscriptionRequest, request: Request) -> dict:
    state = _state(request)
    return await state.task_service.create_subscription(
        body.query, body.brands, body.interval_hours
    )


@router.get("/subscriptions")
async def list_subscriptions(request: Request) -> dict:
    return await _state(request).task_service.list_subscriptions()


@router.delete("/subscriptions/{sub_id}", status_code=status.HTTP_200_OK)
async def delete_subscription(sub_id: str, request: Request) -> dict:
    state = _state(request)
    try:
        return await state.task_service.delete_subscription(sub_id)
    except TaskNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"subscription not found: {exc}"
        ) from exc


@router.post("/subscriptions/{sub_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_subscription(sub_id: str, request: Request) -> dict:
    """Trigger a subscription re-run (derives brief from query, starts research)."""
    state = _state(request)
    try:
        return await state.task_service.run_subscription(sub_id)
    except TaskNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"subscription not found: {exc}"
        ) from exc


__all__ = ["router"]
