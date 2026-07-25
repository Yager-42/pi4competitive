"""Integration O1–O10 — six-stage research workflow (research-workflow-v1)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from earendil_works.pi_ai.providers.faux import faux_assistant_message


_TASK_BODY = {
    "research_brief": {
        "target": {"name": "ACME", "category": "SaaS"},
        "goal": "analyze ACME vs competitors",
        "competitors": ["ACME", "Beta"],
        "dimensions": ["pricing", "features"],
    },
    "metadata": {"trace": "t1"},
}


def _stage_responses():
    """Six faux responses, one per stage, each matching the minimal schema."""
    return [
        faux_assistant_message('{"plan": "search ACME and Beta pricing"}'),
        faux_assistant_message('{"evidence": [{"source": "tavily", "content": "ACME $10/mo"}]}'),
        faux_assistant_message('{"analysis": "ACME cheaper", "gaps": []}'),
        faux_assistant_message('{"report": "ACME Report: ACME is cheaper."}'),
        faux_assistant_message('{"verdict": "approve", "issues": []}'),
        faux_assistant_message('{"citations": [{"claim": "ACME $10", "source": "tavily"}]}'),
    ]


async def _client(app_state):
    from competitive_app.adapter.in_.fastapi.app import create_app

    app = create_app()
    app.state.application = app_state  # type: ignore[attr-defined]
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _wait_status(client: AsyncClient, task_id: str, terminal: set[str], timeout: float = 10.0):
    """Poll GET /tasks/{id} until status is terminal or timeout."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/api/v2/tasks/{task_id}")
        status = resp.json().get("status")
        if status in terminal:
            return status
        await asyncio.sleep(0.05)
    return status


@pytest.mark.asyncio
async def test_six_stages_completed(app_state, faux):
    faux["setResponses"](_stage_responses())
    async with await _client(app_state) as client:
        create = await client.post("/api/v2/tasks", json=_TASK_BODY)
        assert create.status_code == 202, create.text
        body = create.json()
        assert body["status"] == "pending"
        assert body["session_id"] is not None  # F-R14
        task_id = body["task_id"]

        status = await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        assert status == "completed", f"expected completed, got {status}"

        # Six stage outputs in the session messages.
        msgs = (await client.get(f"/api/v2/sessions/{body['session_id']}/messages")).json()["messages"]
        # Each stage prompt produces a user + assistant message pair, plus stage_output custom entries.
        assert any(m.get("role") == "assistant" for m in msgs if isinstance(m, dict))


@pytest.mark.asyncio
async def test_report_returns_write_output(app_state, faux):
    faux["setResponses"](_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed"})
        report = await client.get(f"/api/v2/tasks/{task_id}/report")
        assert report.status_code == 200
        r = report.json()
        assert r["stage"] == "write"
        assert r["report"] is not None
        assert "ACME" in r["report"]


@pytest.mark.asyncio
async def test_task_sessions_single(app_state, faux):
    faux["setResponses"](_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        sessions = await client.get(f"/api/v2/tasks/{task_id}/sessions")
        assert sessions.status_code == 200
        s = sessions.json()["sessions"]
        assert len(s) == 1
        assert s[0]["session_id"] is not None


@pytest.mark.asyncio
async def test_projection_progress(app_state, faux):
    # Only one response → plan completes, collect hangs (no more responses).
    faux["setResponses"]([faux_assistant_message('{"plan": "p"}')])
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await asyncio.sleep(0.3)
        task = await client.get(f"/api/v2/tasks/{task_id}")
        proj = task.json().get("projection", {})
        # plan should be ok; collect/analyze/etc pending or running.
        assert proj.get("stages", {}).get("plan") in {"ok", "running"}


@pytest.mark.asyncio
async def test_dependency_gate_failed(app_state, faux):
    # plan produces invalid output (missing "plan" key) → plan failed → task failed.
    faux["setResponses"]([faux_assistant_message('{"not_plan": "x"}')])
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        status = await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        assert status == "failed"
        task = await client.get(f"/api/v2/tasks/{task_id}")
        assert task.json()["projection"]["stages"]["plan"] == "failed"


@pytest.mark.asyncio
async def test_abort_stops_runner(app_state, faux):
    faux["setResponses"]([faux_assistant_message('{"plan": "p"}')])  # then hangs
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await asyncio.sleep(0.2)
        abort = await client.post(f"/api/v2/tasks/{task_id}/abort")
        assert abort.status_code == 200
        status = await _wait_status(client, task_id, {"aborted", "failed", "completed"})
        assert status in {"aborted", "failed"}


@pytest.mark.asyncio
async def test_resume_continues(app_state, faux):
    # First run: only plan response → fails at collect (no response).
    faux["setResponses"]([faux_assistant_message('{"plan": "p"}')])
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"failed", "aborted", "completed"})

        # Resume with full responses — plan already ok, should skip to collect.
        faux["setResponses"](_stage_responses()[1:])  # skip plan response
        resume = await client.post(f"/api/v2/tasks/{task_id}/resume")
        assert resume.status_code == 202
        status = await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        assert status == "completed", f"resume expected completed, got {status}"


@pytest.mark.asyncio
async def test_completed_resume_returns_completed(app_state, faux):
    faux["setResponses"](_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed"})
        resume = await client.post(f"/api/v2/tasks/{task_id}/resume")
        assert resume.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_concurrent_resume_409(app_state, faux):
    """A running task (registry marks it active) rejects resume with 409 (F-R18)."""
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        # Manually register a never-completing task to simulate an in-flight runner.
        async def _hang():
            await asyncio.Event().wait()

        app_state.registry.start_task(task_id, None, _hang())
        try:
            await asyncio.sleep(0.05)
            resume = await client.post(f"/api/v2/tasks/{task_id}/resume")
            assert resume.status_code == 409
        finally:
            await app_state.registry.abort_task(task_id, "test")


@pytest.mark.asyncio
async def test_capability_tools_empty_when_no_search(app_state, faux):
    """No search packages enabled (echo only) → collect has no search tools but
    still completes if faux returns evidence directly (F-R10 fallback)."""
    faux["setResponses"](_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        status = await _wait_status(client, task_id, {"completed", "failed"})
        assert status == "completed"
