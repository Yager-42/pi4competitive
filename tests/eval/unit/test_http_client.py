"""http_client: W1 POST /tasks + poll + GET report (D4)."""

from __future__ import annotations

import httpx
import pytest
from eval.runner.http_client import CompetitiveAppClient


@pytest.mark.asyncio
async def test_submit_and_poll_returns_completed():
    transport = httpx.MockTransport(lambda req: _route(req))
    client = CompetitiveAppClient(base_url="http://test", transport=transport)
    result = await client.run_task(
        research_brief={
            "target": {"name": "x", "category": "benchmark"},
            "goal": "Compare A vs B",
            "competitors": ["A", "B"],
            "dimensions": ["price"],
        },
        search_overrides={"max_queries": 20, "max_wall_seconds": 720},
        timeout=30,
    )
    assert result.terminal_status == "completed"
    assert "Markdown table" in result.report_markdown
    assert result.task_id == "task-1"


def _route(req: httpx.Request) -> httpx.Response:
    path = req.url.path
    if path == "/api/v2/tasks" and req.method == "POST":
        return httpx.Response(202, json={"task_id": "task-1"})
    if path.startswith("/api/v2/tasks/task-1"):
        if req.method == "GET" and path == "/api/v2/tasks/task-1":
            return httpx.Response(
                200,
                json={
                    "task_id": "task-1",
                    "status": "completed",
                    "projection": {"report_title": "x"},
                },
            )
        if path == "/api/v2/tasks/task-1/sessions":
            return httpx.Response(200, json={"sessions": []})
    if path == "/api/v2/reports/task-1":
        return httpx.Response(
            200,
            json={"ok": True, "markdown": "Markdown table here", "report_id": "task-1"},
        )
    if path == "/api/v2/tasks/task-1/abort":
        return httpx.Response(200, json={"task_id": "task-1", "status": "aborted"})
    return httpx.Response(404)


@pytest.mark.asyncio
async def test_submit_aborts_on_timeout():
    call_count = {"n": 0}

    def route(req):
        call_count["n"] += 1
        if req.url.path == "/api/v2/tasks" and req.method == "POST":
            return httpx.Response(202, json={"task_id": "task-1"})
        if req.url.path == "/api/v2/tasks/task-1/abort":
            return httpx.Response(200, json={"status": "aborted"})
        # task never completes
        return httpx.Response(
            200, json={"task_id": "task-1", "status": "running", "projection": {}}
        )

    transport = httpx.MockTransport(route)
    client = CompetitiveAppClient(base_url="http://test", transport=transport)
    result = await client.run_task(
        research_brief={
            "target": {"name": "x", "category": "benchmark"},
            "goal": "g",
            "competitors": ["A"],
            "dimensions": ["d"],
        },
        search_overrides={},
        timeout=2,  # 2s
        poll_interval=0.2,
    )
    assert result.terminal_status == "aborted"
