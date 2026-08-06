"""Integration — query-listed products guaranteed as competitors (v0.2.8).

When the user's query explicitly lists products ("为飞书、钉钉、企业微信做 SWOT")
and both discover + derive LLM omit them (misidentify subject as category),
the regex fallback (_regex_brands) + _coerce_competitors must_include guarantees
those products reach brief.competitors and get searched.
"""
from __future__ import annotations

import json

import pytest

from tests.competitive_app.integration.test_workflow import _client, _wait_status


def _discover_category_resp() -> str:
    # discover misidentifies: subject = category, competitors = foreign rivals
    # (mirrors the real bug: "飞书、钉钉、企业微信" treated as category, not products)
    return json.dumps(
        {"subject": "企业协作平台", "domain": "企业软件", "competitors": ["Slack", "Teams", "Zoom"]}
    )


def _derive_resp_no_feishu() -> str:
    # derive LLM omits 飞书/钉钉/企业微信 (picks from discovered candidates only)
    return json.dumps(
        {
            "target": {"name": "企业协作平台", "category": "企业软件"},
            "goal": "SWOT of enterprise collab platforms",
            "competitors": ["Slack", "Teams"],
            "dimensions": ["功能对比"],
        }
    )


@pytest.mark.asyncio
async def test_query_listed_products_in_brief_via_skip_clarify(app_state, faux, mock_fetch_tool) -> None:
    """skip_clarify path: query lists 飞书/钉钉/企业微信; LLM omits → regex fallback."""
    from tests.competitive_app.integration.test_workflow import _full_three_stage_responses

    faux["setResponses"]([_discover_category_resp(), _derive_resp_no_feishu()] + _full_three_stage_responses())
    async with await _client(app_state) as client:
        # skip_clarify: derive brief directly (subscription-style path, no human Q&A)
        create = await client.post(
            "/api/v2/tasks",
            json={"query": "为飞书、钉钉、企业微信做一份结构化 SWOT 竞争分析", "skip_clarify": True},
        )
        # skip_clarify isn't a public body field → likely 422; use the research_brief path instead
        if create.status_code != 202:
            pytest.skip("skip_clarify not exposed via /tasks body; tested via service directly")
        task_id = create.json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed", "aborted"})

        task = (await client.get(f"/api/v2/tasks/{task_id}")).json()
        # brief is in session; check via /reports or projection brands
        proj = task.get("projection", {}) or {}
        brands = proj.get("brands") or []
        # regex fallback must have forced 飞书/钉钉 into competitors → they appear as brands
        assert "飞书" in brands or "钉钉" in brands, f"query-listed products missing: {brands}"


@pytest.mark.asyncio
async def test_query_listed_products_in_brief_via_service(app_state, faux, mock_fetch_tool) -> None:
    """Direct service call: create_task(query, skip_clarify=True) → brief has query products."""
    from tests.competitive_app.integration.test_workflow import _full_three_stage_responses

    faux["setResponses"]([_discover_category_resp(), _derive_resp_no_feishu()] + _full_three_stage_responses())
    result = await app_state.task_service.create_task(
        query="为飞书、钉钉、企业微信做一份结构化 SWOT 竞争分析",
        skip_clarify=True,
    )
    task_id = result["task_id"]
    await _wait_status_by_state(app_state, task_id)
    task = await app_state.store.get_task(task_id)
    # brief stored in session; load via _load_research_brief
    brief = await app_state.task_service._load_research_brief(task["session_id"])
    assert brief is not None, "brief not recoverable"
    comps = brief.competitors
    # regex fallback (must_include) forced query-listed products in despite LLM omitting
    assert "飞书" in comps or "钉钉" in comps, f"query-listed products missing from {comps}"


async def _wait_status_by_state(app_state, task_id: str, timeout: float = 10.0) -> None:
    import asyncio

    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        t = await app_state.store.get_task(task_id)
        if t.get("status") in {"completed", "failed", "aborted"}:
            return
        await asyncio.sleep(0.05)
