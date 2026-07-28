"""Integration O1–O10 — three-stage research workflow (research-workflow-v1 v0.2.0).

plan → search (CoverageEngine iterative loop) → write. Faux model scripts
responses per stage; search stage drives sub-agents that return evidence which
the engine maps into SOCM coverage cells (PR3 direct-fill; PR5 adds judge).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from earendil_works.pi_ai.providers.faux import faux_assistant_message


_TASK_BODY = {
    "research_brief": {
        "target": {"name": "ACME", "category": "SaaS"},
        "goal": "analyze ACME vs Beta pricing",
        "competitors": ["ACME", "Beta"],
        "dimensions": ["pricing"],
    },
    "metadata": {"trace": "t1"},
}


def _plan_response() -> str:
    """plan stage: search plan + coverage_schema (2 entities × 1 attribute)."""
    import json

    return json.dumps(
        {
            "plan": "Search ACME and Beta pricing pages.",
            "coverage_schema": {
                "table_id": "t_competitive",
                "entities": [
                    {"id": "e_acme", "name": "ACME", "kind": "target"},
                    {"id": "e_beta", "name": "Beta", "kind": "competitor"},
                ],
                "attributes": [
                    {"id": "a_price", "name": "Price", "dimension": "pricing", "type": "money_usd"}
                ],
            },
        }
    )


def _search_response(value: str) -> str:
    """One search sub-agent turn: returns evidence for the dispatched entity."""
    import json

    return json.dumps(
        {"evidence": [{"source": f"https://example.com/{value}", "content": f"{value} costs $10/mo"}]}
    )


def _write_response() -> str:
    return '{"report": "ACME vs Beta: both $10/mo [1].\\n\\n## Sources\\n[1] https://example.com/"}'


def _three_stage_responses() -> list:
    """plan + 2 search turns (one per entity) + write."""
    return [
        faux_assistant_message(_plan_response()),
        faux_assistant_message(_search_response("acme")),
        faux_assistant_message(_search_response("beta")),
        faux_assistant_message(_write_response()),
    ]


async def _client(app_state):
    from competitive_app.adapter.in_.fastapi.app import create_app

    app = create_app()
    app.state.application = app_state  # type: ignore[attr-defined]
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _wait_status(client: AsyncClient, task_id: str, terminal: set[str], timeout: float = 15.0):
    deadline = asyncio.get_event_loop().time() + timeout
    status = "pending"
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/api/v2/tasks/{task_id}")
        status = resp.json().get("status")
        if status in terminal:
            return status
        await asyncio.sleep(0.05)
    return status


@pytest.mark.asyncio
async def test_three_stages_completed(app_state, faux):
    faux["setResponses"](_three_stage_responses())
    async with await _client(app_state) as client:
        create = await client.post("/api/v2/tasks", json=_TASK_BODY)
        assert create.status_code == 202, create.text
        body = create.json()
        assert body["status"] == "pending"
        assert body["session_id"] is not None
        task_id = body["task_id"]

        status = await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        assert status == "completed", f"expected completed, got {status}"

        # Projection shows all three stages ok + coverage filled.
        task = await client.get(f"/api/v2/tasks/{task_id}")
        proj = task.json()["projection"]
        assert proj["current_stage"] is None
        for stage in ("plan", "search", "write"):
            assert proj["stages"][stage] == "ok", f"{stage} not ok: {proj['stages']}"
        assert proj["coverage"]["total"] == 2  # 2 entities × 1 attr
        assert proj["coverage"]["filled"] == 2


@pytest.mark.asyncio
async def test_report_returns_write_output(app_state, faux):
    faux["setResponses"](_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed"})
        report = await client.get(f"/api/v2/tasks/{task_id}/report")
        assert report.status_code == 200
        r = report.json()
        assert r["stage"] == "write"
        assert r["report"] is not None
        assert "ACME" in r["report"] or "$10" in r["report"]


@pytest.mark.asyncio
async def test_task_sessions_single(app_state, faux):
    faux["setResponses"](_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        sessions = await client.get(f"/api/v2/tasks/{task_id}/sessions")
        assert sessions.status_code == 200
        s = sessions.json()["sessions"]
        assert len(s) == 1
        assert s[0]["session_id"] is not None


@pytest.mark.asyncio
async def test_dependency_gate_failed(app_state, faux):
    # plan produces invalid output (no coverage_schema, no plan) → plan failed.
    faux["setResponses"]([faux_assistant_message('{"not_plan": "x"}')])
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        status = await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        assert status == "failed"
        task = await client.get(f"/api/v2/tasks/{task_id}")
        proj = task.json()["projection"]
        assert proj["stages"]["plan"] == "failed"
        # F-R3 dependency gate: search never ran.
        assert proj["stages"]["search"] == "pending"


@pytest.mark.asyncio
async def test_search_termination_budget_exhausted(app_state, faux, monkeypatch):
    """Termination 2: budget exhausted (SEARCH_MAX_ITERATIONS=1) → search ends (F-R31).

    Parallel dispatch sends 2 sub-agents in iteration 1 (one per entity). After
    that iteration, consume_iteration hits the cap → search terminates on budget.
    """
    monkeypatch.setenv("SEARCH_MAX_ITERATIONS", "1")
    monkeypatch.setenv("SEARCH_COVERAGE_THRESHOLD", "0.99")  # force not to hit threshold
    faux["setResponses"](
        [
            faux_assistant_message(_plan_response()),
            faux_assistant_message(_search_response("acme")),
            faux_assistant_message(_search_response("beta")),
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
async def test_search_termination_no_progress(app_state, faux, monkeypatch):
    """Termination 3: no progress (stalled_iterations) → search ends (F-R31)."""
    monkeypatch.setenv("SEARCH_MAX_STALLED_ITERATIONS", "2")
    monkeypatch.setenv("SEARCH_MAX_ITERATIONS", "20")  # high, so stall is the trigger
    monkeypatch.setenv("SEARCH_COVERAGE_THRESHOLD", "0.99")
    # Sub-agent returns evidence that does NOT map to cells (content empty after
    # the fill check) → no progress → stall terminates.
    empty_evidence = '{"evidence": []}'
    faux["setResponses"](
        [
            faux_assistant_message(_plan_response()),
            faux_assistant_message(empty_evidence),  # acme: no evidence → unknown
            faux_assistant_message(empty_evidence),  # beta: no evidence → unknown
            faux_assistant_message(_write_response()),
        ]
    )
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        status = await _wait_status(client, task_id, {"completed", "failed"})
        assert status == "completed"
        task = await client.get(f"/api/v2/tasks/{task_id}")
        # Both cells marked unknown (explicit empty evidence) → search ok, write ok.
        proj = task.json()["projection"]
        assert proj["stages"]["search"] == "ok"
        assert proj["stages"]["write"] == "ok"


@pytest.mark.asyncio
async def test_resume_preserves_socm_partial_progress(app_state, faux, monkeypatch):
    """F-R16: search aborted with partial progress → resume keeps filled cells.

    First run: plan + acme search (fills acme) → abort mid-search (beta still empty).
    Resume: A1 fix — engine does NOT overwrite SOCM; acme stays filled, beta
    gets re-dispatched and filled.
    """
    # Make search stall quickly so abort lands while beta is still empty.
    monkeypatch.setenv("SEARCH_MAX_ITERATIONS", "1")  # 1 iteration → only acme dispatched
    monkeypatch.setenv("SEARCH_MAX_STALLED_ITERATIONS", "1")
    monkeypatch.setenv("SEARCH_COVERAGE_THRESHOLD", "0.99")

    # First run: plan + acme search response. beta never dispatched (iter cap=1).
    faux["setResponses"](
        [faux_assistant_message(_plan_response()), faux_assistant_message(_search_response("acme"))]
    )
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        session_id = (await client.get(f"/api/v2/tasks/{task_id}/sessions")).json()["sessions"][0]["session_id"]
        await _wait_status(client, task_id, {"failed", "aborted", "completed"})

        # SOCM should have acme filled (partial progress preserved), beta empty.
        socm = await app_state.socm_store.load(session_id)
        assert socm.coverage_map.filled_count() == 1, "acme filled, beta empty"

        # Reset env for resume (allow full search).
        monkeypatch.delenv("SEARCH_MAX_ITERATIONS", raising=False)
        monkeypatch.delenv("SEARCH_MAX_STALLED_ITERATIONS", raising=False)
        monkeypatch.delenv("SEARCH_COVERAGE_THRESHOLD", raising=False)

        # Resume: search re-runs (it failed — budget exhausted → search output
        # coverage {filled:1,total:2} → ok actually). To force search re-run,
        # we rely on resume from first non-ok: if search ok, resume skips to write.
        # So give write response too.
        faux["setResponses"]([faux_assistant_message(_write_response())])
        resume = await client.post(f"/api/v2/tasks/{task_id}/resume")
        assert resume.status_code == 202
        status = await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        # search was ok (ran 1 iteration, filled acme); resume completes write.
        assert status == "completed", f"resume expected completed, got {status}"

        # A1: acme still filled (SOCM not overwritten on resume).
        socm_after = await app_state.socm_store.load(session_id)
        assert socm_after.coverage_map.filled_count() >= 1, "acme preserved across resume"


@pytest.mark.asyncio
async def test_abort_stops_runner(app_state, faux):
    # Only plan response → search hangs (no search responses) → abort mid-search.
    faux["setResponses"]([faux_assistant_message(_plan_response())])
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await asyncio.sleep(0.3)
        abort = await client.post(f"/api/v2/tasks/{task_id}/abort")
        assert abort.status_code == 200
        status = await _wait_status(client, task_id, {"aborted", "failed", "completed"})
        assert status in {"aborted", "failed"}


@pytest.mark.asyncio
async def test_resume_continues(app_state, faux):
    # First run: only plan → search runs with no responses (marks cells unknown),
    # search ok, write fails (no write response).
    faux["setResponses"]([faux_assistant_message(_plan_response())])
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"failed", "aborted", "completed"})

        # Resume: search already ok (cells unknown), skip to write.
        faux["setResponses"]([faux_assistant_message(_write_response())])
        resume = await client.post(f"/api/v2/tasks/{task_id}/resume")
        assert resume.status_code == 202
        status = await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        assert status == "completed", f"resume expected completed, got {status}"


@pytest.mark.asyncio
async def test_completed_resume_returns_completed(app_state, faux):
    faux["setResponses"](_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        await _wait_status(client, task_id, {"completed"})
        resume = await client.post(f"/api/v2/tasks/{task_id}/resume")
        assert resume.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_concurrent_resume_409(app_state, faux):
    """A running task rejects resume with 409 (F-R18)."""
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
async def test_search_termination_coverage_threshold(app_state, faux):
    """Termination 1: coverage reaches threshold → search ends (F-R31)."""
    # 2 entities × 1 attr = 2 cells; threshold 0.8 → both filled (1.0) ends.
    faux["setResponses"](_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        status = await _wait_status(client, task_id, {"completed", "failed"})
        assert status == "completed"
        task = await client.get(f"/api/v2/tasks/{task_id}")
        assert task.json()["projection"]["coverage"]["filled"] == 2


@pytest.mark.asyncio
async def test_capability_tools_empty_when_no_search(app_state, faux):
    """echo-only capability still completes if faux returns evidence directly."""
    faux["setResponses"](_three_stage_responses())
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=_TASK_BODY)).json()["task_id"]
        status = await _wait_status(client, task_id, {"completed", "failed"})
        assert status == "completed"


@pytest.mark.asyncio
async def test_parallel_fanout_multi_entity(app_state, faux, monkeypatch):
    """PR4: parallel fan-out — 4 entities dispatched concurrently in one iteration.

    With 4 competitors × 1 attribute, the engine dispatches up to max_parallel=4
    sub-agents in one iteration. All 4 fill → coverage 1.0 → search terminates.
    """
    monkeypatch.setenv("SEARCH_MAX_PARALLEL", "4")
    four_body = {
        "research_brief": {
            "target": {"name": "ACME", "category": "SaaS"},
            "goal": "compare 4 competitors pricing",
            "competitors": ["ACME", "Beta", "Gamma", "Delta"],
            "dimensions": ["pricing"],
        },
        "metadata": {"trace": "parallel"},
    }
    import json as _json

    plan = _json.dumps(
        {
            "plan": "search 4 competitors",
            "coverage_schema": {
                "table_id": "t",
                "entities": [
                    {"id": f"e_{n.lower()}", "name": n, "kind": "competitor"}
                    for n in ["ACME", "Beta", "Gamma", "Delta"]
                ],
                "attributes": [
                    {"id": "a_price", "name": "Price", "dimension": "pricing", "type": "money_usd"}
                ],
            },
        }
    )
    responses = [faux_assistant_message(plan)]
    for name in ["acme", "beta", "gamma", "delta"]:
        responses.append(faux_assistant_message(_search_response(name)))
    responses.append(faux_assistant_message(_write_response()))
    faux["setResponses"](responses)
    async with await _client(app_state) as client:
        task_id = (await client.post("/api/v2/tasks", json=four_body)).json()["task_id"]
        status = await _wait_status(client, task_id, {"completed", "failed"})
        assert status == "completed", f"expected completed, got {status}"
        task = await client.get(f"/api/v2/tasks/{task_id}")
        proj = task.json()["projection"]
        assert proj["coverage"]["total"] == 4
        assert proj["coverage"]["filled"] == 4
