"""Contract O3 — routes registered under /api/v2 (feature F-A2 / v0.3.1)."""
from __future__ import annotations

from pathlib import Path

import pytest

EXPECTED_PATHS = {
    "/api/v2/sessions",
    "/api/v2/sessions/{session_id}",
    "/api/v2/sessions/{session_id}/prompt",
    "/api/v2/sessions/{session_id}/abort",
    "/api/v2/sessions/{session_id}/messages",
    "/api/v2/tasks",
    "/api/v2/tasks/{task_id}",
    "/api/v2/tasks/{task_id}/resume",
    "/api/v2/tasks/{task_id}/abort",
    "/api/v2/tasks/{task_id}/report",
    "/api/v2/tasks/{task_id}/sessions",
    "/api/v2/reports",  # v0.3.1
    "/api/v2/reports/{task_id}",  # v0.3.1
    "/api/v2/tasks/{task_id}/stream",  # v0.3.1 SSE
    "/api/v2/tasks/{task_id}/trace",  # v0.3.2
    "/api/v2/reports/{task_id}/refine",  # v0.3.2
    "/api/v2/reports/{task_id}/feedback",  # v0.3.2
    "/api/v2/tasks/{task_id}/clarify",  # v0.3.3
    "/api/v2/evidences",  # v0.3.3
    "/api/v2/dashboard",  # v0.3.3
    "/api/v2/subscriptions",  # v0.3.3
    "/api/v2/subscriptions/{sub_id}",  # v0.3.3
    "/api/v2/subscriptions/{sub_id}/run",  # v0.3.3
    "/api/v2/llm/ping",  # v0.3.4
    "/api/v2/meta",  # v0.3.4
    "/api/v2/health",
}


@pytest.mark.asyncio
async def test_routes_registered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USE_FAUX", "1")
    monkeypatch.setenv("SESSIONS_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("APP_DB", str(tmp_path / "app.db"))
    monkeypatch.setenv("SESSIONS_CWD", "test")

    from competitive_app.adapter.in_.fastapi.app import create_app

    app = create_app()
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/openapi.json")
    assert resp.status_code == 200, resp.text
    schema = resp.json()
    actual = set(schema["paths"].keys())
    missing = EXPECTED_PATHS - actual
    extra_api = actual - EXPECTED_PATHS - {"/"}
    assert not missing, f"missing routes: {missing}"
    assert not extra_api, f"unexpected routes: {extra_api}"

    # v0.3.0: 14. v0.3.1: +3 (reports×2, stream) = 17. v0.3.2: +3 (trace, refine, feedback) = 20.
    # v0.3.3: +7 (clarify, evidences, dashboard, subscriptions×4) = 27.
    # v0.3.4: +2 (llm/ping, meta) = 29.
    route_count = 0
    for path, methods in schema["paths"].items():
        if path.startswith("/api/v2/"):
            route_count += len(methods)
    assert route_count == 29, f"expected 29 routes, got {route_count}"
