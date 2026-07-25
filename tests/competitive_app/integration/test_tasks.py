"""Integration O6/O7 — tasks placeholder lifecycle + resume/abort boundary + delete cascade."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


async def _client(app_state):
    from competitive_app.adapter.in_.fastapi.app import create_app

    app = create_app()
    app.state.application = app_state  # type: ignore[attr-defined]
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


_TASK_BODY = {
    "research_brief": {"target": {"name": "Acme"}, "goal": "analyze Acme"},
    "competitor_discovery": {"candidates": []},
    "metadata": {"trace": "t1"},
}


@pytest.mark.asyncio
async def test_task_placeholder_lifecycle(app_state):
    async with await _client(app_state) as client:
        create = await client.post("/api/v2/tasks", json=_TASK_BODY)
        assert create.status_code == 202, create.text
        body = create.json()
        assert body["status"] == "pending"
        assert body["session_id"] is None
        task_id = body["task_id"]

        # Placeholder runner flips to completed quickly.
        get = await client.get(f"/api/v2/tasks/{task_id}")
        assert get.status_code == 200
        assert get.json()["status"] in {"pending", "running", "completed"}

        report = await client.get(f"/api/v2/tasks/{task_id}/report")
        assert report.status_code == 200
        assert report.json()["report"] is None
        assert "frozen" in report.json()["note"]

        sessions = await client.get(f"/api/v2/tasks/{task_id}/sessions")
        assert sessions.status_code == 200
        assert sessions.json()["sessions"] == []


@pytest.mark.asyncio
async def test_task_resume_completed_returns_completed(app_state):
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        # Wait for placeholder to finish.
        for _ in range(50):
            status = (await client.get(f"/api/v2/tasks/{task_id}")).json()["status"]
            if status == "completed":
                break
            await _idle()
        resume = await client.post(f"/api/v2/tasks/{task_id}/resume")
        assert resume.status_code == 202
        assert resume.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_task_abort_terminal_is_noop_on_status(app_state):
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        for _ in range(50):
            if (await client.get(f"/api/v2/tasks/{task_id}")).json()["status"] == "completed":
                break
            await _idle()
        abort = await client.post(f"/api/v2/tasks/{task_id}/abort")
        assert abort.status_code == 200
        assert abort.json()["status"] == "aborted"
        # status unchanged (terminal sticky)
        assert (await client.get(f"/api/v2/tasks/{task_id}")).json()["status"] == "completed"


@pytest.mark.asyncio
async def test_task_delete_returns_404_after(app_state):
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        dele = await client.delete(f"/api/v2/tasks/{task_id}")
        assert dele.status_code == 204
        get = await client.get(f"/api/v2/tasks/{task_id}")
        assert get.status_code == 404


@pytest.mark.asyncio
async def test_task_not_found_404(app_state):
    async with await _client(app_state) as client:
        assert (await client.get("/api/v2/tasks/nope")).status_code == 404


async def _idle() -> None:
    import asyncio

    await asyncio.sleep(0.01)
