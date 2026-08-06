"""Integration — per-task search_overrides reach CoverageEngine Budget (v0.3.5).

POST /tasks with search_overrides → persisted in metadata → _run_research reads
→ ResearchRunner → CoverageEngine applies Budget override. Verified by reading
the SOCM search_state.json after run: budget.max_queries/max_wall_seconds reflect
the override (not env default).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.competitive_app.integration.test_workflow import _TASK_BODY, _client, _wait_status


@pytest.mark.asyncio
async def test_search_overrides_persisted_in_metadata(app_state, faux, mock_fetch_tool) -> None:
    """search_overrides clamped + stored in task metadata (resume source, F-R16)."""
    from tests.competitive_app.integration.test_workflow import _full_three_stage_responses

    faux["setResponses"](_full_three_stage_responses())
    async with await _client(app_state) as client:
        create = await client.post(
            "/api/v2/tasks",
            json={**_TASK_BODY, "search_overrides": {"max_parallel": 8, "max_queries": 50}},
        )
        assert create.status_code == 202, create.text
        task_id = create.json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed", "aborted"})

        task = (await client.get(f"/api/v2/tasks/{task_id}")).json()
        meta = task.get("metadata", {}) or {}
        ov = meta.get("search_overrides", {})
        assert ov.get("max_parallel") == 8
        assert ov.get("max_queries") == 50


@pytest.mark.asyncio
async def test_search_overrides_clamped_on_create(app_state, faux) -> None:
    """Out-of-range values clamped (not 422); stored clamped in metadata."""
    async with await _client(app_state) as client:
        create = await client.post(
            "/api/v2/tasks",
            json={
                "research_brief": _TASK_BODY["research_brief"],
                "metadata": {"trace": "clamp"},
                "search_overrides": {"max_parallel": 999, "coverage_threshold": -1.0},
            },
        )
        assert create.status_code == 202, create.text
        task_id = create.json()["task_id"]
        task = (await client.get(f"/api/v2/tasks/{task_id}")).json()
        ov = (task.get("metadata", {}) or {}).get("search_overrides", {})
        assert ov == {"max_parallel": 16, "coverage_threshold": 0.05}


@pytest.mark.asyncio
async def test_budget_override_reaches_socm(app_state, faux, mock_fetch_tool) -> None:
    """search_overrides max_queries/max_wall_seconds applied to SOCM Budget."""
    from tests.competitive_app.integration.test_workflow import _full_three_stage_responses

    faux["setResponses"](_full_three_stage_responses())
    async with await _client(app_state) as client:
        create = await client.post(
            "/api/v2/tasks",
            json={**_TASK_BODY, "search_overrides": {"max_queries": 5, "max_wall_seconds": 99}},
        )
        task_id = create.json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed", "aborted"})

        session_id = create.json().get("session_id")
        assert session_id
        # SOCM at <sessions_root>/<session_id>/search_state.json
        socm_file = Path(app_state.config.sessions_root) / session_id / "search_state.json"
        assert socm_file.is_file(), f"SOCM missing: {socm_file}"
        socm = json.loads(socm_file.read_text(encoding="utf-8"))
        budget = socm.get("budget", {})
        assert budget.get("max_queries") == 5
        assert budget.get("max_wall_seconds") == 99


@pytest.mark.asyncio
async def test_no_search_overrides_backward_compat(app_state, faux, mock_fetch_tool) -> None:
    """Tasks without search_overrides use env/Budget defaults (no regression)."""
    from tests.competitive_app.integration.test_workflow import _full_three_stage_responses

    faux["setResponses"](_full_three_stage_responses())
    async with await _client(app_state) as client:
        create = await client.post("/api/v2/tasks", json=_TASK_BODY)  # no search_overrides
        task_id = create.json()["task_id"]
        status = await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        assert status == "completed", f"backward-compat run failed: {status}"
