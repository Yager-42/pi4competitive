"""B-group routes — Agent sessions (5 routes, real).

Contract §3.2 / feature F-A19/F-A20. Routes only call SessionService; they do
not touch pi_agent / aiosqlite directly (contract G2).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from ....application.workflow.session_service import (
    ModelResolutionError,
    SessionConflictError,
    SessionNotFoundError,
)
from .dto import PromptRequest, SessionCreateRequest

router = APIRouter(prefix="/api/v2", tags=["sessions"])


def _state(request: Request):
    from .app import get_state

    return get_state(request.app)


@router.post("/sessions", status_code=status.HTTP_200_OK)
async def create_session(body: SessionCreateRequest, request: Request) -> dict:
    state = _state(request)
    try:
        return await state.session_service.create_session(
            model=body.model,
            system_prompt=body.system_prompt,
            metadata=body.metadata,
            cwd=state.config.sessions_cwd,
        )
    except ModelResolutionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, request: Request) -> dict:
    state = _state(request)
    try:
        return await state.session_service.get_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"session not found: {exc}") from exc


@router.post("/sessions/{session_id}/prompt")
async def prompt_session(session_id: str, body: PromptRequest, request: Request) -> dict:
    state = _state(request)
    try:
        return await state.session_service.prompt(session_id, body.content)
    except SessionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"session not found: {exc}") from exc
    except SessionConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ModelResolutionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/abort")
async def abort_session(session_id: str, request: Request) -> dict:
    state = _state(request)
    # Best-effort abort; 404 if the session was never indexed.
    try:
        await state.session_service.get_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"session not found: {exc}") from exc
    return await state.session_service.abort(session_id)


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str, request: Request) -> dict:
    state = _state(request)
    try:
        return await state.session_service.messages(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"session not found: {exc}") from exc


__all__ = ["router"]
