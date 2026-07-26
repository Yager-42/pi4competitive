"""Live L1 — six-stage research workflow against a real provider.

research-workflow-v1 §6.2 L1: real provider key → POST /tasks runs the six
stages over the network → /report returns non-empty markdown.

Marked @pytest.mark.live; skipped without key (conftest L2).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = [pytest.mark.live, pytest.mark.asyncio]


_TASK_BODY = {
    "research_brief": {
        "target": {"name": "Notion", "category": "note-taking SaaS"},
        "goal": "Compare Notion vs Obsidian for personal note-taking",
        "competitors": ["Obsidian"],
        "dimensions": ["pricing", "features"],
    },
    "metadata": {"trace": "live-l1"},
}


async def _client(state):
    from competitive_app.adapter.in_.fastapi.app import create_app

    app = create_app()
    app.state.application = state  # type: ignore[attr-defined]
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _wait_terminal(client: AsyncClient, task_id: str, timeout: float = 180.0) -> str:
    deadline = asyncio.get_event_loop().time() + timeout
    status = "pending"
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/api/v2/tasks/{task_id}")
        status = resp.json().get("status")
        if status in {"completed", "failed", "aborted"}:
            return status
        await asyncio.sleep(1.0)
    return status


async def test_live_six_stages_real_provider(tmp_path: Path, live_env) -> None:
    import os

    os.environ["SESSIONS_ROOT"] = str(tmp_path / "sessions")
    os.environ["APP_DB"] = str(tmp_path / "app.db")
    os.environ["SESSIONS_CWD"] = "live-test"
    # Use the default whitelist (echo + search_*); search packages load when
    # their env keys are present, fail-closed otherwise.

    from competitive_app.wiring import build_application_state, load_config_from_env

    state = await build_application_state(load_config_from_env())
    try:
        async with await _client(state) as client:
            create = await client.post("/api/v2/tasks", json=_TASK_BODY)
            assert create.status_code == 202, create.text
            task_id = create.json()["task_id"]

            status = await _wait_terminal(client, task_id, timeout=240.0)
            assert status == "completed", f"live run did not complete: {status}"

            report = await client.get(f"/api/v2/tasks/{task_id}/report")
            assert report.status_code == 200
            r = report.json()
            assert r["stage"] == "write"
            assert r["report"], "live report markdown must be non-empty (L1)"
    finally:
        await state.shutdown()
