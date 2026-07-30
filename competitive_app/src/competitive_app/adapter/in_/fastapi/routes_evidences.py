"""Evidences route — GET /evidences (v0.3.3).

Global evidence library: cross-task queryable evidence flattened from each
task's SOCM at completion. Routes only call TaskService (contract G2).
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/v2", tags=["evidences"])


def _state(request: Request):
    from .app import get_state

    return get_state(request.app)


@router.get("/evidences")
async def list_evidences(
    request: Request,
    brand: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    """Query the global evidence library with optional filters + facets."""
    state = _state(request)
    return await state.task_service.list_evidences(
        brand=brand or None,
        source_type=source_type or None,
        min_confidence=min_confidence,
        limit=limit,
    )


__all__ = ["router"]
