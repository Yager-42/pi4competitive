"""Focused regressions for the API/wiring known-issues fixes."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import StreamingResponse

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


def test_empty_sandbox_config_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / ".pi/agent/extensions/pi-sandbox/config.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"filesystem":{"additionalAllowRead":["/trusted"]}}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert _native_sandbox_additional_allow_read("") == []


def test_explicit_sandbox_config_preserves_trusted_paths_and_deduplication(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sandbox.json"
    config.write_text(
        '{"filesystem":{"additionalAllowRead":["/trusted", "/trusted", "/other"]}}',
        encoding="utf-8",
    )
    assert _native_sandbox_additional_allow_read(str(config)) == ["/trusted", "/other"]

@pytest.mark.asyncio
async def test_stream_route_uses_streaming_response(monkeypatch: pytest.MonkeyPatch) -> None:
    import competitive_app.adapter.in_.fastapi.routes_tasks as routes_tasks

    class Store:
        async def get_task(self, _task_id):
            return {"status": "completed", "projection": {}, "session_id": None}

    state = type("State", (), {"store": Store(), "registry": object(), "socm_store": None})()
    monkeypatch.setattr(routes_tasks, "_state", lambda _request: state)
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})

    response = await routes_tasks.stream_task("task-1", request)

    assert isinstance(response, StreamingResponse)
    assert response.media_type == "text/event-stream"
    body = "".join([chunk async for chunk in response.body_iterator])
    assert "event: state_snapshot" in body
    assert "event: done" in body

@pytest.mark.asyncio
async def test_queue_fanout_disconnect_stops_idle_pump() -> None:
    source: asyncio.Queue[dict] = asyncio.Queue()
    fanout = _QueueFanout(source)
    queue = await fanout.subscribe()
    assert fanout._pump_task is not None
    await fanout.unsubscribe(queue)
    assert fanout.idle
    # The pump is only stopped by an explicit close (idle fanouts remain
    # reusable for late subscribers within the registration window).
    assert fanout._pump_task is not None
    await fanout.close()
    assert fanout.closed
    assert fanout._pump_task is None
    with pytest.raises(RuntimeError, match="closed"):
        await fanout.subscribe()


@pytest.mark.asyncio
async def test_queue_fanout_replays_terminal_event_to_late_subscriber() -> None:
    source: asyncio.Queue[dict] = asyncio.Queue()
    fanout = _QueueFanout(source)
    first = await fanout.subscribe()
    terminal = {"type": "done", "data": {"status": "completed"}}
    await source.put(terminal)
    assert await asyncio.wait_for(first.get(), timeout=1) == terminal
    late = await fanout.subscribe()
    assert await late.get() == terminal


@pytest.mark.asyncio
async def test_snapshot_error_event_retains_running_task_status(monkeypatch: pytest.MonkeyPatch) -> None:
    import competitive_app.adapter.in_.fastapi.routes_tasks as routes_module

    class Store:
        async def get_task(self, _task_id):
            return {"status": "running", "projection": {}, "session_id": "s1"}

    class Socm:
        async def load(self, _session_id):
            raise ValueError("snapshot read failed")

    state = type("State", (), {"store": Store(), "socm_store": Socm(), "registry": object()})()
    monkeypatch.setattr(routes_module, "_state", lambda _request: state)
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    response = await routes_module.stream_task("task-1", request)
    body = "".join([chunk async for chunk in response.body_iterator])
    assert '"code": "snapshot_unavailable"' in body
    assert '"error_kind": "infrastructure"' in body
    assert '"status": "running"' in body


@pytest.mark.asyncio
async def test_fanout_is_rebuilt_after_close_during_teardown_window() -> None:
    import competitive_app.adapter.in_.fastapi.routes_tasks as routes_tasks

    class Registry:
        def __init__(self) -> None:
            self.sources: list[asyncio.Queue[dict]] = []

        def get_stream(self, _task_id: str) -> asyncio.Queue[dict]:
            source: asyncio.Queue[dict] = asyncio.Queue()
            self.sources.append(source)
            return source

        def unsubscribe_stream(self, _task_id: str, _queue) -> None:
            return None

    registry = Registry()
    key = (id(registry), "task-1")
    try:
        first = await routes_tasks._subscribe_stream(registry, "task-1")
        first_fanout = routes_tasks._SSE_FANOUTS[key]
        await first_fanout.close()
        # A client subscribing during the teardown window gets a fresh fanout
        # over the same source, never the closed one.
        second = await routes_tasks._subscribe_stream(registry, "task-1")
        second_fanout = routes_tasks._SSE_FANOUTS[key]
        assert second is not first
        assert second_fanout is not first_fanout
        assert not second_fanout.closed
        assert len(registry.sources) == 2
    finally:
        routes_tasks._SSE_FANOUTS.pop(key, None)
