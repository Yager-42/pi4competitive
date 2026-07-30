"""Integration — GET /tasks/{id}/stream SSE (v0.3.1).

Verifies the SSE event contract: state_snapshot on connect, live event sequence
(stage_start → ... → done), terminal-task snapshot+done, 404 for missing task.
Uses faux model + mock_fetch_tool to drive a real three-stage run.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient

from tests.competitive_app.integration.test_workflow import (
    _TASK_BODY,
    _client,
    _full_three_stage_responses,
    _wait_status,
)


async def _drain_sse_events(client: AsyncClient, url: str, until: set[str],
                            max_events: int = 200) -> list[tuple[str, dict]]:
    """Open an SSE stream and collect (event_type, data) until a type in `until`."""
    events: list[tuple[str, dict]] = []
    async with client.stream("GET", url, timeout=30.0) as resp:
        assert resp.status_code == 200
        event_type: str | None = None
        data_lines: list[str] = []
        async for line in resp.aiter_lines():
            if line.startswith(":"):  # heartbeat comment
                continue
            if line.startswith("event: "):
                event_type = line[len("event: "):].strip()
            elif line.startswith("data: "):
                data_lines.append(line[len("data: "):])
            elif line == "" and event_type is not None:  # frame boundary
                data = json.loads("".join(data_lines)) if data_lines else {}
                events.append((event_type, data))
                if event_type in until:
                    return events
                event_type = None
                data_lines = []
            if len(events) >= max_events:
                break
    return events


@pytest.mark.asyncio
async def test_stream_404_when_task_missing(app_state, faux):
    async with await _client(app_state) as client:
        resp = await client.get("/api/v2/tasks/nonexistent/stream")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_stream_terminal_task_pushes_snapshot_and_done(app_state, faux, mock_fetch_tool):
    """Connect to an already-completed task → snapshot + done, then close."""
    faux["setResponses"](_full_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed"})
        assert (await client.get(f"/api/v2/tasks/{task_id}")).json()["status"] == "completed"

        events = await _drain_sse_events(
            client, f"/api/v2/tasks/{task_id}/stream", until={"done"}
        )
    types = [t for t, _ in events]
    assert types[0] == "state_snapshot", f"first event must be snapshot, got {types[0]}"
    assert "done" in types, f"terminal task must push done, got {types}"
    assert types[-1] == "done"


@pytest.mark.asyncio
async def test_stream_live_event_sequence(app_state, faux, mock_fetch_tool):
    """Connect while running → snapshot + full live sequence to done."""
    faux["setResponses"](_full_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        # Connect immediately (task pending→running); drain until done.
        events = await _drain_sse_events(
            client, f"/api/v2/tasks/{task_id}/stream", until={"done", "error"}
        )
    types = [t for t, _ in events]
    # Snapshot first.
    assert types[0] == "state_snapshot"
    # Stage lifecycle events present.
    assert "stage_start" in types, f"missing stage_start: {types}"
    assert "stage_end" in types, f"missing stage_end: {types}"
    # search stage emits coverage_update + (evidence | subagent_start).
    assert "coverage_update" in types, f"missing coverage_update: {types}"
    # Terminal event.
    assert types[-1] in {"done", "error"}, f"last must be terminal: {types[-1]}"
    # report_ready fired (write stage done).
    if "done" in types:
        assert "report_ready" in types, f"missing report_ready before done: {types}"


@pytest.mark.asyncio
async def test_stream_snapshot_has_projection_fields(app_state, faux, mock_fetch_tool):
    """state_snapshot data carries status/stages/coverage."""
    faux["setResponses"](_full_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed"})
        events = await _drain_sse_events(
            client, f"/api/v2/tasks/{task_id}/stream", until={"done"}
        )
    snapshot_data = events[0][1]
    assert snapshot_data["task_id"] == task_id
    assert "status" in snapshot_data
    assert "stages" in snapshot_data
    assert "coverage" in snapshot_data
