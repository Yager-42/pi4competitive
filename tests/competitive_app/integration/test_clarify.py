"""Integration — clarify flow (v0.3.3).

POST /tasks {query} → awaiting_clarify + 3 questions (LLM discovers competitors).
POST /tasks/{id}/clarify {answers} → derive brief → start research → completed.
Backward compat: {research_brief} path unchanged. Degradation + error cases.
"""
from __future__ import annotations

import json

import pytest

from earendil_works.pi_ai.providers.faux import faux_assistant_message

from tests.competitive_app.integration.test_workflow import (
    _TASK_BODY,
    _client,
    _full_three_stage_responses,
    _wait_status,
)


def _discover_resp(subject: str = "ACME", domain: str = "SaaS", comps=None) -> str:
    if comps is None:
        comps = ["Beta", "Gamma"]
    return json.dumps(
        {"subject": subject, "domain": domain, "competitors": comps}
    )


def _derive_resp() -> str:
    return json.dumps(
        {
            "target": {"name": "ACME", "category": "SaaS"},
            "goal": "analyze ACME vs Beta pricing",
            "competitors": ["ACME", "Beta"],
            "dimensions": ["pricing"],
        }
    )


@pytest.mark.asyncio
async def test_query_returns_awaiting_clarify_with_questions(app_state, faux):
    """POST /tasks {query} → awaiting_clarify; questions include focus+market
    (+competitors when discovery found candidates)."""
    faux["setResponses"]([faux_assistant_message(_discover_resp())])
    async with await _client(app_state) as client:
        resp = await client.post("/api/v2/tasks", json={"query": "ACME vs Beta 定价"})
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["status"] == "awaiting_clarify"
        assert body["session_id"] is None  # session deferred
        qids = {q["id"] for q in body["questions"]}
        assert {"focus", "market"} <= qids
        assert "competitors" in qids  # conditional: discovery found comps
        comp_q = next(q for q in body["questions"] if q["id"] == "competitors")
        assert comp_q["type"] == "multi"
        assert comp_q["options"]  # has discovered competitors


@pytest.mark.asyncio
async def test_query_no_competitors_omits_competitors_question(app_state, faux):
    """Discovery with empty competitors → only focus+market questions (Q7)."""
    faux["setResponses"]([faux_assistant_message(_discover_resp(comps=[]))])
    async with await _client(app_state) as client:
        body = (await client.post("/api/v2/tasks", json={"query": "ACME"})).json()
        assert body["status"] == "awaiting_clarify"
        qids = {q["id"] for q in body["questions"]}
        assert qids == {"focus", "market"}


@pytest.mark.asyncio
async def test_submit_clarify_derives_brief_and_runs(app_state, faux, mock_fetch_tool):
    """Full flow: query → clarify → submit → research → completed."""
    faux["setResponses"](
        [faux_assistant_message(_discover_resp()), faux_assistant_message(_derive_resp())]
        + _full_three_stage_responses()
    )
    async with await _client(app_state) as client:
        create = await client.post("/api/v2/tasks", json={"query": "ACME vs Beta 定价"})
        task_id = create.json()["task_id"]
        assert create.json()["status"] == "awaiting_clarify"

        submit = await client.post(
            f"/api/v2/tasks/{task_id}/clarify",
            json={"answers": [
                {"id": "competitors", "value": ["Beta"]},
                {"id": "focus", "value": ["定价策略"]},
                {"id": "market", "value": "中国大陆"},
            ]},
        )
        assert submit.status_code == 202, submit.text
        assert submit.json()["status"] == "pending"
        assert submit.json()["session_id"]  # session created on submit

        status = await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        assert status == "completed", f"expected completed, got {status}"


@pytest.mark.asyncio
async def test_research_brief_path_unchanged(app_state, faux, mock_fetch_tool):
    """Backward compat: {research_brief} runs immediately (no awaiting_clarify)."""
    faux["setResponses"](_full_three_stage_responses())
    async with await _client(app_state) as client:
        create = await client.post("/api/v2/tasks", json=_TASK_BODY)
        assert create.status_code == 202
        assert create.json()["status"] == "pending"
        assert create.json()["session_id"]  # session created immediately


@pytest.mark.asyncio
async def test_create_task_422_when_both_or_neither(app_state, faux):
    async with await _client(app_state) as client:
        # neither
        r1 = await client.post("/api/v2/tasks", json={})
        assert r1.status_code == 422
        # both
        r2 = await client.post("/api/v2/tasks", json={"query": "x", **_TASK_BODY})
        assert r2.status_code == 422


@pytest.mark.asyncio
async def test_clarify_404_unknown_task(app_state, faux):
    async with await _client(app_state) as client:
        resp = await client.post(
            "/api/v2/tasks/nonexistent/clarify", json={"answers": []}
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_clarify_409_when_not_awaiting(app_state, faux, mock_fetch_tool):
    """Clarifying a task that already started (pending) → 409."""
    faux["setResponses"](_full_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        resp = await client.post(
            f"/api/v2/tasks/{task_id}/clarify", json={"answers": []}
        )
        assert resp.status_code == 409


@pytest.mark.asyncio
async def test_discovery_failure_degrades_to_direct_run(app_state, faux, mock_fetch_tool):
    """Q3-A: if discovery LLM returns unusable JSON → skip clarify, run directly.

    The faux response is non-JSON garbage → _try_parse_json fails → degrade path
    derives a fallback brief and starts research immediately (pending, not
    awaiting_clarify)."""
    # garbage discover (degrade) + derive fallback consumes nothing (models ok but
    # parse fails on discover; derive still called with fallback discovered) ...
    # Simpler: models return garbage for discover → degrade. Then _derive_brief is
    # called with empty discovered; give it a valid brief resp, then runner.
    faux["setResponses"](
        [faux_assistant_message("not json at all"), faux_assistant_message(_derive_resp())]
        + _full_three_stage_responses()
    )
    async with await _client(app_state) as client:
        create = await client.post("/api/v2/tasks", json={"query": "ACME"})
        # degrade → pending (not awaiting_clarify)
        assert create.json()["status"] == "pending"
        task_id = create.json()["task_id"]
        status = await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        assert status == "completed", f"expected completed, got {status}"
