"""Integration — dashboard aggregation (v0.3.3).

GET /dashboard returns pure-SQL aggregates over tasks/evidences/task_spans.
Empty DB → all zeros. After a run → reports/evidence_total/token_total > 0.
"""
from __future__ import annotations

import pytest

from tests.competitive_app.integration.test_workflow import (
    _TASK_BODY,
    _client,
    _full_three_stage_responses,
    _wait_status,
)


@pytest.mark.asyncio
async def test_dashboard_empty(app_state, faux):
    async with await _client(app_state) as client:
        body = (await client.get("/api/v2/dashboard")).json()
        assert body["reports"] == 0
        assert body["evidence_total"] == 0
        assert body["token_total"] == 0
        assert body["avg_evidence_per_report"] == 0
        assert body["fact_accuracy"] == 0  # no evidence → 0 (no divide-by-zero)
        assert isinstance(body["tasks_by_status"], dict)


@pytest.mark.asyncio
async def test_dashboard_after_run(app_state, faux, mock_fetch_tool):
    async with await _client(app_state) as client:
        faux["setResponses"](_full_three_stage_responses())
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed", "aborted"})

        body = (await client.get("/api/v2/dashboard")).json()
        assert body["reports"] == 1
        assert body["evidence_total"] > 0
        assert body["token_total"] > 0  # batch2 trace spans feed token_total
        assert body["tasks_total"] >= 1
        assert body["tasks_by_status"].get("completed") == 1


@pytest.mark.asyncio
async def test_dashboard_tasks_by_status_includes_clarify(app_state, faux):
    """An awaiting_clarify task shows up in tasks_by_status."""
    from earendil_works.pi_ai.providers.faux import faux_assistant_message
    import json

    async with await _client(app_state) as client:
        faux["setResponses"](
            [faux_assistant_message(json.dumps({"subject": "ACME", "domain": "SaaS", "competitors": ["Beta"]}))])
        await client.post("/api/v2/tasks", json={"query": "ACME vs Beta"})
        body = (await client.get("/api/v2/dashboard")).json()
        assert body["tasks_by_status"].get("awaiting_clarify", 0) >= 1
