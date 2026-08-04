"""Focused regressions for the API/wiring known-issues fixes."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from competitive_app.adapter.in_.fastapi import app as app_module
from competitive_app.adapter.in_.fastapi.dto import FeedbackRequest
from competitive_app.adapter.in_.fastapi.routes_reports import _require_trusted_local
from competitive_app.adapter.in_.fastapi.routes_tasks import (
    _QueueFanout,
    _build_snapshot,
)
from competitive_app.wiring import _native_sandbox_additional_allow_read


def test_cors_credentials_use_explicit_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    app = app_module.create_app()
    cors = next(m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware")
    assert cors.kwargs["allow_credentials"] is True
    assert "*" not in cors.kwargs["allow_origins"]


def test_cors_wildcard_configuration_is_filtered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "*")
    app = app_module.create_app()
    cors = next(m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware")
    assert cors.kwargs["allow_origins"] == []

def test_feedback_rejects_edited_blocks_above_total() -> None:
    with pytest.raises(ValueError, match="edited_blocks"):
        FeedbackRequest(edited_blocks=3, total_blocks=2)
    assert FeedbackRequest(edited_blocks=2, total_blocks=2).edited_blocks == 2


def _request_with_client(host: str | None) -> Request:
    scope = {"type": "http", "method": "GET", "path": "/", "headers": []}
    if host is not None:
        scope["client"] = (host, 1234)
    return Request(scope)


def test_reports_require_loopback_request() -> None:
    _require_trusted_local(_request_with_client("127.0.0.1"))
    with pytest.raises(HTTPException, match="trusted local"):
        _require_trusted_local(_request_with_client("203.0.113.8"))
    with pytest.raises(HTTPException, match="trusted local"):
        _require_trusted_local(_request_with_client(None))


@pytest.mark.asyncio
async def test_queue_fanout_delivers_each_event_to_each_client() -> None:
    source: asyncio.Queue[dict] = asyncio.Queue()
    fanout = _QueueFanout(source)
    fanout.start()
    left = await fanout.subscribe()
    right = await fanout.subscribe()
    event = {"type": "stage_start", "data": {"stage": "plan"}}
    await source.put(event)
    assert await asyncio.wait_for(left.get(), timeout=1) == event
    assert await asyncio.wait_for(right.get(), timeout=1) == event


@pytest.mark.asyncio
async def test_snapshot_socm_failure_is_not_silently_defaulted() -> None:
    class Store:
        async def get_task(self, _task_id):
            return {"status": "running", "projection": {}, "session_id": "s1"}

    class Socm:
        async def load(self, _session_id):
            raise ValueError("corrupt search_state.json")

    class State:
        store = Store()
        socm_store = Socm()

    with pytest.raises(ValueError, match="corrupt"):
        await _build_snapshot(State(), "task-1")


def test_empty_sandbox_config_uses_documented_home_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / ".pi/agent/extensions/pi-sandbox/config.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"filesystem":{"additionalAllowRead":["/trusted"]}}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert _native_sandbox_additional_allow_read("") == ["/trusted"]


def test_stream_route_uses_streaming_response() -> None:
    # Keep a lightweight smoke check that the app still registers the stream route.
    app = app_module.create_app()
    assert "/api/v2/tasks/{task_id}/stream" in app.openapi()["paths"]
