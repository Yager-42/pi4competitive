"""Dashboard route — GET /dashboard (v0.3.3).

Global aggregation: reports / evidence / claims / coverage / tokens / status
distribution. Pure SQL over the SQLite projection (no SOCM reads). Routes only
call TaskService (contract G2).
"""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v2", tags=["dashboard"])


def _state(request: Request):
    from .app import get_state

    return get_state(request.app)


@router.get("/dashboard")
async def dashboard(request: Request) -> dict:
    return await _state(request).task_service.get_dashboard()


__all__ = ["router"]
