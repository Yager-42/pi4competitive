"""Integration — GET /reports + GET /reports/{task_id} (v0.3.1).

Report list (cards) + structured full report. report_id = task_id. Cards read
from projection (populated on completion); full report real-time assembles
JSONL markdown + SOCM coverage/sources.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

# Reuse the three-stage faux fixtures + helpers from test_workflow.
from tests.competitive_app.integration.test_workflow import (
    _TASK_BODY,
    _client,
    _full_three_stage_responses,
    _wait_status,
)


@pytest.mark.asyncio
async def test_reports_list_empty_when_no_completed(app_state, faux):
    """No completed tasks → empty reports list."""
    async with await _client(app_state) as client:
        resp = await client.get("/api/v2/reports")
        assert resp.status_code == 200
        assert resp.json() == {"reports": []}


@pytest.mark.asyncio
async def test_reports_list_has_card_after_completion(app_state, faux, mock_fetch_tool):
    faux["setResponses"](_full_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed"})

        resp = await client.get("/api/v2/reports")
        assert resp.status_code == 200
        cards = resp.json()["reports"]
        assert any(c["report_id"] == task_id for c in cards), "completed task not in reports"
        card = next(c for c in cards if c["report_id"] == task_id)
        assert card["status"] == "completed"
        # brands = [target.name] + competitors, de-duped: ACME + [ACME, Beta] → [ACME, Beta]
        assert card["brands"] == ["ACME", "Beta"]
        # title populated from write markdown first heading.
        assert card["title"], "report_title should be populated on completion"
        assert card["evidence_count"] >= 0
        assert card["claim_count"] >= 0


@pytest.mark.asyncio
async def test_reports_list_excludes_non_completed(app_state, faux):
    """A pending/failed task must NOT appear in /reports (completed only)."""
    # plan fails → task failed, never completed → not in reports.
    faux["setResponses"]([__import__("earendil_works.pi_ai.providers.faux", fromlist=["faux_assistant_message"]).faux_assistant_message('{"not_plan": "x"}')])
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed"})
        resp = await client.get("/api/v2/reports")
        cards = resp.json()["reports"]
        assert all(c["report_id"] != task_id for c in cards), "failed task leaked into reports"


@pytest.mark.asyncio
async def test_report_full_success(app_state, faux, mock_fetch_tool):
    faux["setResponses"](_full_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed"})

        resp = await client.get(f"/api/v2/reports/{task_id}")
        assert resp.status_code == 200
        r = resp.json()
        assert r["ok"] is True
        assert r["report_id"] == task_id
        assert r["markdown"], "full report markdown must be non-empty"
        assert "coverage" in r
        assert {"filled", "total", "unknown", "conflict", "ratio"} <= set(r["coverage"].keys())
        assert isinstance(r["sources"], list)
        assert r["evidence_count"] >= 0


@pytest.mark.asyncio
async def test_report_full_not_ready_when_running(app_state, faux):
    """Task not completed → {ok:false, message:'report not ready'} (200)."""
    # plan invalid → failed (not completed) → not ready.
    faux["setResponses"]([__import__("earendil_works.pi_ai.providers.faux", fromlist=["faux_assistant_message"]).faux_assistant_message('{"not_plan": "x"}')])
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed"})
        resp = await client.get(f"/api/v2/reports/{task_id}")
        assert resp.status_code == 200
        r = resp.json()
        assert r["ok"] is False
        assert r["message"] == "report not ready"


@pytest.mark.asyncio
async def test_report_full_404_when_not_found(app_state, faux):
    async with await _client(app_state) as client:
        resp = await client.get("/api/v2/reports/nonexistent_task_id")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reports_list_sorted_newest_first(app_state):
    """Two completed tasks → newest (latest created_at) first.

    Inserts two completed tasks directly into the store (bypassing the runner —
    the runner's extension-runtime reuse across two tasks in one test session
    goes stale, which is unrelated to the sort logic under test).
    """
    from competitive_app.domain.stage import empty_projection

    store = app_state.store
    await store.init()
    # Task 1 (older), then task 2 (newer). created_at is set by create_task to now.
    p1 = empty_projection()
    p1["report_title"] = "Older Report"
    await store.create_task(task_id="t_older", query="q1", status="completed",
                            metadata={}, projection=p1, session_id="s1")
    p2 = empty_projection()
    p2["report_title"] = "Newer Report"
    await store.create_task(task_id="t_newer", query="q2", status="completed",
                            metadata={}, projection=p2, session_id="s2")

    async with await _client(app_state) as client:
        resp = await client.get("/api/v2/reports")
        cards = resp.json()["reports"]
        ids = [c["report_id"] for c in cards]
        # t_newer created after t_older → newest first.
        assert ids.index("t_newer") < ids.index("t_older"), f"expected newest first, got {ids}"
