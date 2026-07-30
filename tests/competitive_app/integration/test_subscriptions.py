"""Integration — subscription monitoring (v0.3.3).

CRUD + manual run (no scheduler). run derives a brief from the stored query
(skip_clarify) and starts research, recording the run.
"""
from __future__ import annotations

import json

import pytest
from earendil_works.pi_ai.providers.faux import faux_assistant_message

from tests.competitive_app.integration.test_workflow import (
    _client,
    _full_three_stage_responses,
    _wait_status,
)


def _discover_resp() -> str:
    return json.dumps({"subject": "Trae", "domain": "AI IDE", "competitors": ["Cursor", "Windsurf"]})


def _derive_resp() -> str:
    return json.dumps(
        {
            "target": {"name": "Trae", "category": "AI IDE"},
            "goal": "compare Trae vs Cursor",
            "competitors": ["Cursor"],
            "dimensions": ["功能对比", "定价策略"],
        }
    )


@pytest.mark.asyncio
async def test_subscription_crud(app_state, faux):
    async with await _client(app_state) as client:
        create = await client.post(
            "/api/v2/subscriptions", json={"query": "Trae 竞品", "brands": ["Cursor"], "interval_hours": 168}
        )
        assert create.status_code == 201, create.text
        sub = create.json()
        assert sub["query"] == "Trae 竞品"
        assert sub["brands"] == ["Cursor"]
        sub_id = sub["sub_id"]

        listed = (await client.get("/api/v2/subscriptions")).json()["subscriptions"]
        assert any(s["sub_id"] == sub_id for s in listed)

        deleted = await client.delete(f"/api/v2/subscriptions/{sub_id}")
        assert deleted.status_code == 200
        assert deleted.json()["ok"] is True

        listed2 = (await client.get("/api/v2/subscriptions")).json()["subscriptions"]
        assert not any(s["sub_id"] == sub_id for s in listed2)


@pytest.mark.asyncio
async def test_subscription_run_triggers_task(app_state, faux, mock_fetch_tool):
    """POST /subscriptions/{id}/run → derives brief (skip_clarify) → starts task."""
    faux["setResponses"](
        [faux_assistant_message(_discover_resp()), faux_assistant_message(_derive_resp())]
        + _full_three_stage_responses()
    )
    async with await _client(app_state) as client:
        sub = (await client.post("/api/v2/subscriptions", json={"query": "Trae 竞品"})).json()
        sub_id = sub["sub_id"]

        run = await client.post(f"/api/v2/subscriptions/{sub_id}/run")
        assert run.status_code == 202, run.text
        body = run.json()
        assert body["ok"] is True
        task_id = body["task_id"]

        status = await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        assert status == "completed", f"expected completed, got {status}"

        # subscription run history recorded
        listed = (await client.get("/api/v2/subscriptions")).json()["subscriptions"]
        s = next(x for x in listed if x["sub_id"] == sub_id)
        assert s["run_count"] == 1
        assert s["last_task_id"] == task_id
        assert s["last_run_at"]


@pytest.mark.asyncio
async def test_subscription_run_404(app_state, faux):
    async with await _client(app_state) as client:
        resp = await client.post("/api/v2/subscriptions/nonexistent/run")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_subscription_delete_404(app_state, faux):
    async with await _client(app_state) as client:
        resp = await client.delete("/api/v2/subscriptions/nonexistent")
        assert resp.status_code == 404
