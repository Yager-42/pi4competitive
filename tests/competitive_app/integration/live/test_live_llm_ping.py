"""Live — real LLM ping (batch4 v0.3.4).

Env-gated (skips without OPENAI key); not exit-blocking. Verifies a real
completeSimple round-trip through the configured gateway returns ok + model +
latency_ms > 0. Sandbox doubles skip Docker (ping needs no tools).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = [pytest.mark.live, pytest.mark.asyncio]


class _TestToolExecutor:
    """E5 test double: in-process direct execution (never a production path)."""

    async def execute(self, *, scope_id, tool, tool_call_id, params, signal=None, on_update=None):
        del scope_id
        return await tool.execute(tool_call_id, params, signal, on_update)


class _TestSandboxLifecycle:
    """E5 test double: no-op lifecycle for offline App tests."""

    async def release(self, *, session_id):
        return None

    async def destroy(self, *, session_id):
        return None

    async def delete_workspace(self, *, session_id):
        return None

    async def shutdown(self) -> None:
        return None


async def test_live_llm_ping(tmp_path: Path, live_env) -> None:
    import os

    os.environ["SESSIONS_ROOT"] = str(tmp_path / "sessions")
    os.environ["APP_DB"] = str(tmp_path / "app.db")
    os.environ["SESSIONS_CWD"] = "live-ping"

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
            resp = await client.get("/api/v2/llm/ping")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True, f"live ping failed: {body}"
        assert body["model"]
        assert body["latency_ms"] > 0
    finally:
        await state.shutdown()
