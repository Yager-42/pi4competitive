"""Integration — global evidence library (v0.3.3).

GET /evidences returns ACTIVE evidence flattened from completed tasks' SOCM.
Supports brand/source_type/min_confidence filters + facets. Cascade delete.
"""
from __future__ import annotations

import pytest

from tests.competitive_app.integration.test_workflow import (
    _TASK_BODY,
    _client,
    _full_three_stage_responses,
    _wait_status,
)


async def _run_one(client, faux):
    faux["setResponses"](_full_three_stage_responses())
    task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
    await _wait_status(client, task_id, {"completed", "failed", "aborted"})
    return task_id


@pytest.mark.asyncio
async def test_completed_task_indexes_evidences(app_state, faux, mock_fetch_tool):
    async with await _client(app_state) as client:
        await _run_one(client, faux)
        resp = await client.get("/api/v2/evidences")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) > 0, "completed task should index evidence"
        ev = body["items"][0]
        # pi4 evidence is structured: entity/attribute/value/source/confidence.
        assert {"evidence_id", "task_id", "entity", "attribute", "value", "confidence"} <= set(ev.keys())


@pytest.mark.asyncio
async def test_evidences_facets(app_state, faux, mock_fetch_tool):
    async with await _client(app_state) as client:
        await _run_one(client, faux)
        facets = (await client.get("/api/v2/evidences")).json()["facets"]
        assert facets["total"] > 0
        assert isinstance(facets["by_type"], dict)
        assert isinstance(facets["by_brand"], dict)


@pytest.mark.asyncio
async def test_evidences_filter_by_min_confidence(app_state, faux, mock_fetch_tool):
    async with await _client(app_state) as client:
        await _run_one(client, faux)
        high = (await client.get("/api/v2/evidences?min_confidence=0.9")).json()["items"]
        all_ev = (await client.get("/api/v2/evidences")).json()["items"]
        assert len(high) <= len(all_ev)
        assert all(e["confidence"] >= 0.9 for e in high)


@pytest.mark.asyncio
async def test_evidences_filter_by_brand(app_state, faux, mock_fetch_tool):
    async with await _client(app_state) as client:
        await _run_one(client, faux)
        # pick a brand that exists, then filter
        all_ev = (await client.get("/api/v2/evidences")).json()["items"]
        if not all_ev:
            pytest.skip("no evidence")
        brand = all_ev[0]["brand"]
        filtered = (await client.get(f"/api/v2/evidences?brand={brand}")).json()["items"]
        assert all(e["brand"] == brand for e in filtered)
        assert len(filtered) >= 1


@pytest.mark.asyncio
async def test_delete_task_cascades_evidences(app_state, faux, mock_fetch_tool):
    async with await _client(app_state) as client:
        task_id = await _run_one(client, faux)
        before = (await client.get("/api/v2/evidences")).json()["facets"]["total"]
        assert before > 0
        await client.delete(f"/api/v2/tasks/{task_id}")
        items = (await client.get("/api/v2/evidences")).json()["items"]
        assert all(i["task_id"] != task_id for i in items), "cascade delete should remove task evidence"


@pytest.mark.asyncio
async def test_evidences_empty_db(app_state, faux):
    async with await _client(app_state) as client:
        body = (await client.get("/api/v2/evidences")).json()
        assert body["items"] == []
        assert body["facets"]["total"] == 0
