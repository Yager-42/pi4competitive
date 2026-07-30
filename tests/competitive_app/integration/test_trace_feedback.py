"""Integration — trace spans + feedback (v0.3.2).

GET /tasks/{id}/trace returns call-level spans (plan/subagent/judge/write).
POST /reports/{id}/feedback records revision rate.
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
async def test_trace_404_when_task_missing(app_state, faux):
    async with await _client(app_state) as client:
        resp = await client.get("/api/v2/tasks/nonexistent/trace")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_trace_has_spans_after_run(app_state, faux, mock_fetch_tool):
    """A completed three-stage run produces plan/subagent/judge/write spans."""
    faux["setResponses"](_full_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed"})

        resp = await client.get(f"/api/v2/tasks/{task_id}/trace")
        assert resp.status_code == 200
        body = resp.json()
        assert body["task_id"] == task_id
        spans = body["spans"]
        assert isinstance(spans, list)
        assert len(spans) > 0, "run should produce at least one span"
        # span kinds present (plan + write at minimum; search subagent/judge if search ran).
        kinds = {s["kind"] for s in spans}
        assert "plan" in kinds, f"missing plan span: {kinds}"
        assert "write" in kinds, f"missing write span: {kinds}"
        # spans ordered by seq (call order).
        seqs = [s["seq"] for s in spans]
        assert seqs == sorted(seqs), f"spans not ordered by seq: {seqs}"
        # each span has the core fields.
        for s in spans:
            assert {"span_id", "kind", "latency_ms", "prompt_tokens", "completion_tokens"} <= set(s.keys())


@pytest.mark.asyncio
async def test_trace_span_has_latency(app_state, faux, mock_fetch_tool):
    """Spans carry a non-negative latency (real run, even if tokens are 0)."""
    faux["setResponses"](_full_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed"})
        spans = (await client.get(f"/api/v2/tasks/{task_id}/trace")).json()["spans"]
        assert all(s["latency_ms"] >= 0 for s in spans)


@pytest.mark.asyncio
async def test_feedback_records_revision_rate(app_state, faux, mock_fetch_tool):
    """POST /reports/{id}/feedback stores edited/total + returns revision_rate."""
    faux["setResponses"](_full_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed"})

        resp = await client.post(
            f"/api/v2/reports/{task_id}/feedback",
            json={"edited_blocks": 2, "total_blocks": 5, "data": {"note": "fixed price"}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["report_id"] == task_id
        assert body["revision_rate"] == 0.4


@pytest.mark.asyncio
async def test_feedback_zero_total(app_state, faux):
    """total_blocks=0 → revision_rate 0 (no division by zero)."""
    async with await _client(app_state) as client:
        # any task_id works for feedback (it just upserts); use a fresh one via create.
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed"})
        resp = await client.post(
            f"/api/v2/reports/{task_id}/feedback",
            json={"edited_blocks": 0, "total_blocks": 0},
        )
        assert resp.status_code == 200
        assert resp.json()["revision_rate"] == 0.0


@pytest.mark.asyncio
async def test_feedback_404_when_task_missing(app_state, faux):
    async with await _client(app_state) as client:
        resp = await client.post(
            "/api/v2/reports/nonexistent/feedback",
            json={"edited_blocks": 1, "total_blocks": 2},
        )
        assert resp.status_code == 404
