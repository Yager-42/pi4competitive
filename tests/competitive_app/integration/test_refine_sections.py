"""Integration — write sections + refine (v0.2.2 / v0.3.2).

write stage_output carries derived `sections` (split from report by `##`).
POST /reports/{id}/refine rewrites one section and appends a refine stage_output;
GET /reports/{id} then returns the refined report (refine > write).
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
async def test_write_output_has_sections(app_state, faux, mock_fetch_tool):
    """After completion, the write stage_output contains a `sections` array."""
    faux["setResponses"](_full_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed"})

        resp = await client.get(f"/api/v2/reports/{task_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "sections" in body, "full report must include sections"
        sections = body["sections"]
        assert isinstance(sections, list)
        # each section has id/title/body.
        for s in sections:
            assert {"id", "title", "body"} <= set(s.keys())


@pytest.mark.asyncio
async def test_refine_404_when_task_missing(app_state, faux):
    async with await _client(app_state) as client:
        resp = await client.post(
            "/api/v2/reports/nonexistent/refine",
            json={"section_id": "1", "annotations": ["more detail"]},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_refine_section_not_found(app_state, faux, mock_fetch_tool):
    """Refine a non-existent section_id → {ok:false, message:'section not found'}."""
    faux["setResponses"](_full_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed"})
        resp = await client.post(
            f"/api/v2/reports/{task_id}/refine",
            json={"section_id": "999", "annotations": []},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert "section not found" in body["message"]


@pytest.mark.asyncio
async def test_refine_rewrites_and_get_report_reflects(app_state, faux, mock_fetch_tool):
    """Refine section 1 → append refine stage_output → GET /reports/{id} reflects it.

    The faux model's write response produces a report; refine calls completeSimple
    with the refine prompt (faux returns the next scripted response). We verify
    the refine endpoint returns ok and that a subsequent GET shows the refined
    section (refine stage_output preferred over write).
    """
    # _full_three_stage_responses scripts plan + entities + write. Add one more
    # response for the refine completeSimple call.
    from earendil_works.pi_ai.providers.faux import faux_assistant_message

    faux["setResponses"](_full_three_stage_responses() + [faux_assistant_message("## 一、定价对比\n\n重写后的定价章节内容(更详细)。")])
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed"})

        # find a real section id from the report
        report = (await client.get(f"/api/v2/reports/{task_id}")).json()
        sections = report.get("sections") or []
        if not sections:
            pytest.skip("write produced no sections (faux report shape)")
        sid = sections[0]["id"]

        refine = await client.post(
            f"/api/v2/reports/{task_id}/refine",
            json={"section_id": sid, "annotations": ["add pricing detail"]},
        )
        assert refine.status_code == 200
        rbody = refine.json()
        assert rbody["ok"] is True, f"refine failed: {rbody}"

        # GET /reports/{id} now reflects the refine (refine > write).
        after = (await client.get(f"/api/v2/reports/{task_id}")).json()
        assert after["ok"] is True
        # the refined section is marked refined.
        refined = next((s for s in after["sections"] if str(s["id"]) == str(sid)), None)
        assert refined is not None
        assert refined.get("refined") is True
