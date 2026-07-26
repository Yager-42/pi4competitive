"""Health route."""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v2", tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict:
    from .app import get_state

    try:
        state = get_state(request.app)
        active = len(state.registry._tasks)  # type: ignore[attr-defined]
    except RuntimeError:
        active = 0
    return {"status": "ok", "active_workflows": active, "runtime": "pi-agent"}


__all__ = ["router"]
