"""Integration O1–O10 — three-stage research workflow (research-workflow-v1 v0.2.0).

plan → search (CoverageEngine iterative loop) → write. Faux model scripts
responses per stage; search stage drives sub-agents that return evidence which
the engine maps into SOCM coverage cells (PR3 direct-fill; PR5 adds judge).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from earendil_works.pi_ai.providers.faux import faux_assistant_message


_TASK_BODY = {
    "research_brief": {
        "target": {"name": "ACME", "category": "SaaS"},
        "goal": "analyze ACME vs Beta pricing",
        "competitors": ["ACME", "Beta"],
        "dimensions": ["pricing"],
    },
    "metadata": {"trace": "t1"},
}


def _plan_response() -> str:
    """plan stage: search plan + coverage_schema (2 entities × 1 attribute)."""
    import json

    return json.dumps(
        {
            "plan": "Search ACME and Beta pricing pages.",
            "coverage_schema": {
                "table_id": "t_competitive",
                "entities": [
                    {"id": "e_acme", "name": "ACME", "kind": "target"},
                    {"id": "e_beta", "name": "Beta", "kind": "competitor"},
                ],
                "attributes": [
                    {"id": "a_price", "name": "Price", "dimension": "pricing", "type": "money_usd"}
                ],
            },
        }
    )


def _search_response(value: str) -> str:
    """One search sub-agent turn: returns evidence for the dispatched entity."""
    import json

    return json.dumps(
        {"evidence": [{"source": f"https://example.com/{value}", "content": f"{value} costs $10/mo"}]}
    )


def _write_response() -> str:
    return '{"report": "ACME vs Beta: both $10/mo [1].\\n\\n## Sources\\n[1] https://example.com/"}'


def _three_stage_responses() -> list:
    """plan + 2 search turns (one per entity) + write."""
    return [
        faux_assistant_message(_plan_response()),
        faux_assistant_message(_search_response("acme")),
        faux_assistant_message(_search_response("beta")),
        faux_assistant_message(_write_response()),
    ]


async def _client(app_state):
    from competitive_app.adapter.in_.fastapi.app import create_app

    app = create_app()
    app.state.application = app_state  # type: ignore[attr-defined]
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _wait_status(client: AsyncClient, task_id: str, terminal: set[str], timeout: float = 15.0):
    deadline = asyncio.get_event_loop().time() + timeout
    status = "pending"
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/api/v2/tasks/{task_id}")
        status = resp.json().get("status")
        if status in terminal:
            return status
        await asyncio.sleep(0.05)
    return status


@pytest.mark.asyncio
async def test_three_stages_completed(app_state, faux):
    faux["setResponses"](_three_stage_responses())
    async with await _client(app_state) as client:
        create = await client.post("/api/v2/tasks", json=_TASK_BODY)
        assert create.status_code == 202, create.text
        body = create.json()
        assert body["status"] == "pending"
        assert body["session_id"] is not None
        task_id = body["task_id"]

        status = await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        assert status == "completed", f"expected completed, got {status}"

        # Projection shows all three stages ok + coverage filled.
        task = await client.get(f"/api/v2/tasks/{task_id}")
        proj = task.json()["projection"]
        assert proj["current_stage"] is None
        for stage in ("plan", "search", "write"):
            assert proj["stages"][stage] == "ok", f"{stage} not ok: {proj['stages']}"
        assert proj["coverage"]["total"] == 2  # 2 entities × 1 attr
        assert proj["coverage"]["filled"] == 2


@pytest.mark.asyncio
async def test_report_returns_write_output(app_state, faux):
    faux["setResponses"](_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed"})
        report = await client.get(f"/api/v2/tasks/{task_id}/report")
        assert report.status_code == 200
        r = report.json()
        assert r["stage"] == "write"
        assert r["report"] is not None
        assert "ACME" in r["report"] or "$10" in r["report"]


@pytest.mark.asyncio
async def test_task_sessions_single(app_state, faux):
    faux["setResponses"](_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        sessions = await client.get(f"/api/v2/tasks/{task_id}/sessions")
        assert sessions.status_code == 200
        s = sessions.json()["sessions"]
        assert len(s) == 1
        assert s[0]["session_id"] is not None


@pytest.mark.asyncio
async def test_dependency_gate_failed(app_state, faux):
    # plan produces invalid output (no coverage_schema, no plan) → plan failed.
    faux["setResponses"]([faux_assistant_message('{"not_plan": "x"}')])
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        status = await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        assert status == "failed"
        task = await client.get(f"/api/v2/tasks/{task_id}")
        assert task.json()["projection"]["stages"]["plan"] == "failed"


@pytest.mark.asyncio
async def test_abort_stops_runner(app_state, faux):
    # Only plan response → search hangs (no search responses) → abort mid-search.
    faux["setResponses"]([faux_assistant_message(_plan_response())])
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await asyncio.sleep(0.3)
        abort = await client.post(f"/api/v2/tasks/{task_id}/abort")
        assert abort.status_code == 200
        status = await _wait_status(client, task_id, {"aborted", "failed", "completed"})
        assert status in {"aborted", "failed"}


@pytest.mark.asyncio
async def test_resume_continues(app_state, faux):
    # First run: only plan → fails at search (no responses).
    faux["setResponses"]([faux_assistant_message(_plan_response())])
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"failed", "aborted", "completed"})

        # Resume with search + write responses — plan already ok, skip to search.
        faux["setResponses"](
            [
                faux_assistant_message(_search_response("acme")),
                faux_assistant_message(_search_response("beta")),
                faux_assistant_message(_write_response()),
            ]
        )
        resume = await client.post(f"/api/v2/tasks/{task_id}/resume")
        assert resume.status_code == 202
        status = await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        assert status == "completed", f"resume expected completed, got {status}"


@pytest.mark.asyncio
async def test_completed_resume_returns_completed(app_state, faux):
    faux["setResponses"](_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed"})
        resume = await client.post(f"/api/v2/tasks/{task_id}/resume")
        assert resume.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_concurrent_resume_409(app_state, faux):
    """A running task rejects resume with 409 (F-R18)."""
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed", "aborted"})

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
async def test_search_termination_coverage_threshold(app_state, faux):
    """Termination 1: coverage reaches threshold → search ends (F-R31)."""
    # 2 entities × 1 attr = 2 cells; threshold 0.8 → both filled (1.0) ends.
    faux["setResponses"](_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        status = await _wait_status(client, task_id, {"completed", "failed"})
        assert status == "completed"
        task = await client.get(f"/api/v2/tasks/{task_id}")
        assert task.json()["projection"]["coverage"]["filled"] == 2


@pytest.mark.asyncio
async def test_capability_tools_empty_when_no_search(app_state, faux):
    """echo-only capability still completes if faux returns evidence directly."""
    faux["setResponses"](_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        status = await _wait_status(client, task_id, {"completed", "failed"})
        assert status == "completed"
