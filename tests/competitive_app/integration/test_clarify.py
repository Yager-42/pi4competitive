"""Integration — clarify flow (v0.3.3).

POST /tasks {query} → awaiting_clarify + 2–3 questions (LLM discovers competitors).
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


def _discover_resp(
    subject: str = "ACME",
    domain: str = "SaaS",
    comps=None,
    specified_entities: list[str] | None = None,
) -> str:
    if comps is None:
        comps = ["Beta", "Gamma"]
    payload = {"subject": subject, "domain": domain, "competitors": comps}
    if specified_entities is not None:
        payload["specified_entities"] = specified_entities
    return json.dumps(payload)


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
        resp = await client.post("/api/v2/tasks", json={"query": "ACME 的竞品定价分析"})
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
async def test_closed_comparison_omits_competitor_picker_and_persists_fixed_entities(
    app_state, faux
):
    """A user-specified comparison set is fixed before the questionnaire."""
    query = "分析特斯拉、比亚迪、理想在新能源车市场的产品力与定价竞争格局"
    fixed = ["特斯拉", "比亚迪", "理想"]
    faux["setResponses"](
        [
            faux_assistant_message(
                _discover_resp(
                    subject="新能源汽车",
                    domain="新能源汽车",
                    comps=[*fixed, "蔚来", "小鹏"],
                    specified_entities=fixed,
                )
            )
        ]
    )
    async with await _client(app_state) as client:
        create = await client.post("/api/v2/tasks", json={"query": query})
        assert create.status_code == 202, create.text
        body = create.json()
        assert {q["id"] for q in body["questions"]} == {"focus", "market"}
        task = await app_state.store.get_task(body["task_id"])
        discovered = task["metadata"]["clarify"]["discovered"]
        assert discovered["specified_entities"] == fixed


@pytest.mark.asyncio
async def test_closed_comparison_hard_limits_final_brief_to_user_entities(app_state, faux):
    """The second LLM cannot add a discovered, selected, or invented rival."""
    query = "分析特斯拉、比亚迪、理想在新能源车市场的产品力与定价竞争格局"
    fixed = ["特斯拉", "比亚迪", "理想"]
    # Deliberately return an extra rival and a wrong target: post-processing must
    # still turn the closed query into exactly the three user-named entities.
    faux["setResponses"](
        [
            faux_assistant_message(
                json.dumps(
                    {
                        "target": {"name": "蔚来", "category": "新能源汽车"},
                        "goal": "比较新能源车品牌",
                        "competitors": ["蔚来", "特斯拉", "比亚迪", "理想"],
                        "dimensions": ["产品力", "定价策略"],
                    }
                )
            )
        ]
    )
    brief = await app_state.task_service._derive_brief(
        query,
        [],
        {
            "subject": "新能源汽车",
            "domain": "新能源汽车",
            "competitors": [*fixed, "蔚来"],
            "specified_entities": fixed,
        },
        [{"id": "competitors", "value": ["蔚来"]}],
    )
    assert [brief.target.name, *brief.competitors] == fixed


@pytest.mark.asyncio
async def test_submit_clarify_derives_brief_and_runs(app_state, faux, mock_fetch_tool):
    """Full flow: query → clarify → submit → research → completed."""
    faux["setResponses"](
        [faux_assistant_message(_discover_resp()), faux_assistant_message(_derive_resp())]
        + _full_three_stage_responses()
    )
    async with await _client(app_state) as client:
        create = await client.post("/api/v2/tasks", json={"query": "ACME 的竞品定价"})
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
