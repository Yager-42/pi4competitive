"""Integration — three-stage research workflow with PR5 judge Extraction.

plan → search (CoverageEngine: sub-agent fetches pages, judge extracts evidence
into SOCM) → write. Faux model scripts: plan JSON, sub-agent fetch tool_call +
final message, judge JSON array, write report. A mock ``test_fetch`` tool
returns pages with pricing so the judge has content to extract (offline).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from earendil_works.pi_ai.providers.faux import faux_assistant_message, faux_tool_call


def _plan_response(target: str = "ACME", competitor: str = "Beta") -> str:
    return json.dumps(
        {
            "plan": f"Search {target} and {competitor} pricing pages.",
            "coverage_schema": {
                "table_id": "t_competitive",
                "entities": [
                    {"id": "e_acme", "name": target, "kind": "target"},
                    {"id": "e_beta", "name": competitor, "kind": "competitor"},
                ],
                "attributes": [
                    {"id": "a_price", "name": "Price", "dimension": "pricing", "type": "money_usd"}
                ],
            },
        }
    )


def _judge_response(value: str = "$10/mo", slug: str = "acme") -> str:
    """Judge extraction result with a source/excerpt from the fetched slug."""
    source = f"https://example.com/{slug}"
    return json.dumps(
        [
            {
                "attribute": "a_price",
                "value": value,
                "source": source,
                "source_excerpt": f"The plan costs {value} per month.",
                "confidence": 0.9,
            }
        ]
    )


def _write_response() -> str:
    return '{"report": "ACME vs Beta pricing comparison [1].\\n\\n## Sources\\n[1] https://example.com/"}'


_TASK_BODY = {
    "research_brief": {
        "target": {"name": "ACME", "category": "SaaS"},
        "goal": "analyze ACME vs Beta pricing",
        "competitors": ["ACME", "Beta"],
        "dimensions": ["pricing"],
    },
    "metadata": {"trace": "t1"},
}


async def _client(app_state):
    from competitive_app.adapter.in_.fastapi.app import create_app

    app = create_app()
    app.state.application = app_state  # type: ignore[attr-defined]
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _wait_status(client: AsyncClient, task_id: str, terminal: set[str], timeout: float = 20.0):
    deadline = asyncio.get_event_loop().time() + timeout
    status = "pending"
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/api/v2/tasks/{task_id}")
        status = resp.json().get("status")
        if status in terminal:
            return status
        await asyncio.sleep(0.05)
    return status


def _entity_responses(slug: str, price: str) -> list:
    """Serial-dispatch order for one entity: fetch tool_call → final → judge JSON.

    With SEARCH_MAX_PARALLEL=1, the engine dispatches one entity per iteration;
    each iteration consumes: sub-agent fetch(2 responses) + judge(1 response).
    """
    return [
        faux_assistant_message([faux_tool_call("test_fetch", {"url": f"https://example.com/{slug}"})]),
        faux_assistant_message("done searching"),
        faux_assistant_message(_judge_response(price, slug)),
    ]


def _full_three_stage_responses() -> list:
    """plan + 2 entities (fetch/final/judge each) + write, in call order."""
    return [
        faux_assistant_message(_plan_response()),
        *_entity_responses("acme", "$10/mo"),
        *_entity_responses("beta", "$20/mo"),
        faux_assistant_message(_write_response()),
    ]


@pytest.mark.asyncio
async def test_three_stages_completed_with_judge_extraction(app_state, faux, mock_fetch_tool):
    """plan → search (fetch + judge) → write; SOCM filled via judge (F-R29/F-R30)."""
    faux["setResponses"](_full_three_stage_responses())
    async with await _client(app_state) as client:
        create = await client.post("/api/v2/tasks", json=_TASK_BODY)
        assert create.status_code == 202, create.text
        task_id = create.json()["task_id"]
        status = await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        assert status == "completed", f"expected completed, got {status}"

        task = await client.get(f"/api/v2/tasks/{task_id}")
        proj = task.json()["projection"]
        assert proj["current_stage"] is None
        for stage in ("plan", "search", "write"):
            assert proj["stages"][stage] == "ok", f"{stage}: {proj['stages']}"
        assert proj["coverage"]["total"] == 2
        assert proj["coverage"]["filled"] == 2


@pytest.mark.asyncio
async def test_report_returns_write_output(app_state, faux, mock_fetch_tool):
    faux["setResponses"](_full_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed"})
        report = await client.get(f"/api/v2/tasks/{task_id}/report")
        assert report.status_code == 200
        r = report.json()
        assert r["stage"] == "write"
        assert r["report"] is not None


@pytest.mark.asyncio
async def test_task_sessions_single(app_state, faux, mock_fetch_tool):
    faux["setResponses"](_full_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed"})
        sessions = await client.get(f"/api/v2/tasks/{task_id}/sessions")
        assert sessions.status_code == 200
        s = sessions.json()["sessions"]
        assert len(s) == 1
        assert s[0]["session_id"] is not None


@pytest.mark.asyncio
async def test_dependency_gate_failed(app_state, faux):
    """plan produces invalid output → plan failed → search never runs (F-R3)."""
    faux["setResponses"]([faux_assistant_message('{"not_plan": "x"}')])
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        status = await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        assert status == "failed"
        task = await client.get(f"/api/v2/tasks/{task_id}")
        proj = task.json()["projection"]
        assert proj["stages"]["plan"] == "failed"
        assert proj["stages"]["search"] == "pending"


@pytest.mark.asyncio
async def test_abort_stops_runner(app_state, faux, mock_fetch_tool):
    """Abort mid-search stops the runner."""
    faux["setResponses"](
        [
            faux_assistant_message(_plan_response()),
            faux_assistant_message([faux_tool_call("test_fetch", {"url": "https://example.com/acme"})]),
            # No final / judge / write responses → search hangs → abort.
        ]
    )
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await asyncio.sleep(0.3)
        abort = await client.post(f"/api/v2/tasks/{task_id}/abort")
        assert abort.status_code == 200
        status = await _wait_status(client, task_id, {"aborted", "failed", "completed"})
        assert status in {"aborted", "failed"}


@pytest.mark.asyncio
async def test_resume_continues(app_state, faux, mock_fetch_tool):
    """First run: plan only → search fails (no fetch responses). Resume completes."""
    faux["setResponses"]([faux_assistant_message(_plan_response())])
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"failed", "aborted", "completed"})

        # Resume: search re-runs (it failed) with full fetch + judge + write.
        faux["setResponses"](
            [
                *_entity_responses("acme", "$10/mo"),
                *_entity_responses("beta", "$20/mo"),
                faux_assistant_message(_write_response()),
            ]
        )
        resume = await client.post(f"/api/v2/tasks/{task_id}/resume")
        assert resume.status_code == 202
        status = await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        assert status == "completed", f"resume expected completed, got {status}"


@pytest.mark.asyncio
async def test_completed_resume_returns_completed(app_state, faux, mock_fetch_tool):
    faux["setResponses"](_full_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed"})
        resume = await client.post(f"/api/v2/tasks/{task_id}/resume")
        assert resume.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_concurrent_resume_409(app_state, faux, mock_fetch_tool):
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed", "aborted"})

        async def _hang():
            await asyncio.Event().wait()

        app_state.registry.start_task(task_id, None, _hang())
        try:
            await asyncio.sleep(0.05)
            resume = await client.post(f"/api/v2/tasks/{task_id}/resume")
            assert resume.status_code == 409
        finally:
            await app_state.registry.abort_task(task_id, "test")


@pytest.mark.asyncio
async def test_search_termination_coverage_threshold(app_state, faux, mock_fetch_tool):
    """Termination 1: both cells filled by judge → coverage 1.0 → search ends."""
    faux["setResponses"](_full_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        status = await _wait_status(client, task_id, {"completed", "failed"})
        assert status == "completed"
        task = await client.get(f"/api/v2/tasks/{task_id}")
        assert task.json()["projection"]["coverage"]["filled"] == 2


@pytest.mark.asyncio
async def test_search_termination_budget_exhausted(app_state, faux, mock_fetch_tool, monkeypatch):
    """Termination 2: SEARCH_MAX_ITERATIONS=1 → search ends after one round."""
    monkeypatch.setenv("SEARCH_MAX_ITERATIONS", "1")
    monkeypatch.setenv("SEARCH_COVERAGE_THRESHOLD", "0.99")
    faux["setResponses"](
        [
            faux_assistant_message(_plan_response()),
            *_entity_responses("acme", "$10/mo"),
            *_entity_responses("beta", "$20/mo"),
            faux_assistant_message(_write_response()),
        ]
    )
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        status = await _wait_status(client, task_id, {"completed", "failed"})
        assert status == "completed"
        task = await client.get(f"/api/v2/tasks/{task_id}")
        proj = task.json()["projection"]
        assert proj["stages"]["search"] == "ok"
        assert proj["stages"]["write"] == "ok"


@pytest.mark.asyncio
async def test_search_termination_no_progress(app_state, faux, mock_fetch_tool, monkeypatch):
    """Termination 3: judge returns no findings → no fill → stall terminates."""
    monkeypatch.setenv("SEARCH_MAX_STALLED_ITERATIONS", "2")
    monkeypatch.setenv("SEARCH_MAX_ITERATIONS", "20")
    monkeypatch.setenv("SEARCH_COVERAGE_THRESHOLD", "0.99")
    empty_judge = "[]"
    # 2 iterations × 2 entities = 4 sub-agent rounds + 4 judge calls (all empty).
    responses = [faux_assistant_message(_plan_response())]
    for _ in range(4):
        responses.append(faux_assistant_message([faux_tool_call("test_fetch", {"url": "https://x"})]))
        responses.append(faux_assistant_message("done"))
        responses.append(faux_assistant_message(empty_judge))
    responses.append(faux_assistant_message(_write_response()))
    faux["setResponses"](responses)
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        status = await _wait_status(client, task_id, {"completed", "failed"})
        assert status == "completed"
        task = await client.get(f"/api/v2/tasks/{task_id}")
        proj = task.json()["projection"]
        assert proj["stages"]["search"] == "ok"
        assert proj["coverage"]["filled"] == 0


@pytest.mark.asyncio
async def test_resume_preserves_socm_partial_progress(app_state, faux, mock_fetch_tool, monkeypatch):
    """F-R16: search aborted with partial progress → resume keeps filled cells."""
    monkeypatch.setenv("SEARCH_MAX_ITERATIONS", "1")
    monkeypatch.setenv("SEARCH_MAX_STALLED_ITERATIONS", "1")
    monkeypatch.setenv("SEARCH_COVERAGE_THRESHOLD", "0.99")
    # First run: plan + 1 entity fetch/judge (fills acme); beta not dispatched (iter cap=1).
    faux["setResponses"](
        [
            faux_assistant_message(_plan_response()),
            faux_assistant_message([faux_tool_call("test_fetch", {"url": "https://example.com/acme"})]),
            faux_assistant_message("done"),
            faux_assistant_message(_judge_response("$10/mo", "acme")),
        ]
    )
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        session_id = (await client.get(f"/api/v2/tasks/{task_id}/sessions")).json()["sessions"][0]["session_id"]
        await _wait_status(client, task_id, {"failed", "aborted", "completed"})

        socm = await app_state.socm_store.load(session_id)
        assert socm.coverage_map.filled_count() >= 1, "acme filled before resume"

        monkeypatch.delenv("SEARCH_MAX_ITERATIONS", raising=False)
        monkeypatch.delenv("SEARCH_MAX_STALLED_ITERATIONS", raising=False)
        monkeypatch.delenv("SEARCH_COVERAGE_THRESHOLD", raising=False)
        faux["setResponses"]([faux_assistant_message(_write_response())])
        await client.post(f"/api/v2/tasks/{task_id}/resume")
        status = await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        assert status == "completed", f"resume expected completed, got {status}"

        socm_after = await app_state.socm_store.load(session_id)
        assert socm_after.coverage_map.filled_count() >= 1, "acme preserved across resume"
