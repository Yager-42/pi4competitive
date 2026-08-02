"""LLM diagnostic route — GET /llm/ping (batch4 v0.3.4).

Real LLM round-trip: one ``completeSimple`` call with a trivial prompt. Returns
``{ok, model, reply, latency_ms}`` on success; ``{ok: False, reason, message}``
on not-configured or call error. Routes only call TaskService (contract G2).
"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v2", tags=["llm"])


def _state(request: Request):
    from .app import get_state

    return get_state(request.app)


@router.get("/llm/ping")
async def llm_ping(request: Request) -> dict:
    return await _state(request).task_service.ping_llm()


__all__ = ["router"]
