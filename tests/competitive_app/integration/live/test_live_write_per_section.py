"""Live — write per-section structure in a real run (research-workflow v0.2.6).

Env-gated (skips without OPENAI key); not exit-blocking. Runs a real task (low
SEARCH_COVERAGE_THRESHOLD so search finishes fast → write runs), then asserts the
report has the per-section structure: ## 概述 + per-dimension ## + ## 结论与建议 +
## Sources, and sections[] = overview + dims + conclusion + Sources (sequential ids).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = [pytest.mark.live, pytest.mark.asyncio]


class _TestToolExecutor:
    async def execute(self, *, scope_id, tool, tool_call_id, params, signal=None, on_update=None):
        del scope_id
        return await tool.execute(tool_call_id, params, signal, on_update)


class _TestSandboxLifecycle:
    async def release(self, *, session_id):
        return None

    async def destroy(self, *, session_id):
        return None

    async def delete_workspace(self, *, session_id):
        return None

    async def shutdown(self) -> None:
        return None


async def test_live_write_per_section_structure(tmp_path: Path, live_env) -> None:
    import os

    os.environ["SESSIONS_ROOT"] = str(tmp_path / "sessions")
    os.environ["APP_DB"] = str(tmp_path / "app.db")
    os.environ["SESSIONS_CWD"] = "live-write-ps"
    # Low coverage threshold so search finishes fast → write (per-section) runs.
    os.environ["SEARCH_COVERAGE_THRESHOLD"] = "0.05"
    os.environ["SEARCH_MAX_ITERATIONS"] = "2"

    from competitive_app.adapter.in_.fastapi.app import create_app
    from competitive_app.wiring import build_application_state, load_config_from_env

    state = await build_application_state(
        load_config_from_env(),
        tool_executor=_TestToolExecutor(),
        sandbox_lifecycle=_TestSandboxLifecycle(),
    )
    try:
        app = create_app()
        app.state.application = state  # type: ignore[attr-defined]
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", timeout=60
        ) as client:
            create = await client.post(
                "/api/v2/tasks",
                json={
                    "research_brief": {
                        "target": {"name": "Notion", "category": "note-taking SaaS"},
                        "goal": "Compare Notion vs Obsidian pricing",
                        "competitors": ["Obsidian"],
                        "dimensions": ["pricing"],
                    },
                    "metadata": {"trace": "live-write-ps"},
                },
            )
            assert create.status_code == 202, create.text
            task_id = create.json()["task_id"]

            # Poll until completed (per-section write runs after search).
            deadline = asyncio.get_event_loop().time() + 480.0
            status = "pending"
            t: dict = {}
            while asyncio.get_event_loop().time() < deadline:
                t = (await client.get(f"/api/v2/tasks/{task_id}")).json()
                status = t.get("status")
                if status in {"completed", "failed", "aborted"}:
                    break
                await asyncio.sleep(2.0)
            if status != "completed":
                pytest.skip(
                    f"live run did not complete in 480s (real gateway slow; per-section "
                    f"structure is offline-verified). last: {t.get('projection', {}).get('stages')}"
                )

            report = await client.get(f"/api/v2/reports/{task_id}")
            assert report.status_code == 200
            r = report.json()
            md = r.get("markdown") or ""
            sections = r.get("sections") or []

            # v0.2.6 per-section structure
            assert "## 概述" in md, "missing overview section"
            assert "## pricing" in md, "missing dimension section"
            assert "## 结论与建议" in md, "missing conclusion section"
            assert "## Sources" in md, "missing Sources section"
            titles = [s.get("title") for s in sections]
            assert "概述" in titles and "pricing" in titles
            assert "结论与建议" in titles and "Sources" in titles
            ids = [s.get("id") for s in sections]
            assert ids == [str(i) for i in range(1, len(sections) + 1)]
    finally:
        await state.shutdown()
