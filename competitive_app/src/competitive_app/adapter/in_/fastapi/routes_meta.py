"""Meta diagnostic route — GET /meta (batch4 v0.3.4).

Snapshot: versions + llm config + capabilities + runtime. Never leaks
``OPENAI_BASE_URL`` / ``OPENAI_API_KEY`` values. Routes only call
ApplicationState (contract G2).
"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v2", tags=["meta"])


def _state(request: Request):
    from .app import get_state

    return get_state(request.app)


@router.get("/meta")
async def meta(request: Request) -> dict:
    return _state(request).get_meta()


__all__ = ["router"]
