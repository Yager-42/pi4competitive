"""Contract O3 — 14 routes registered under /api/v2 (feature F-A2)."""
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
    "/api/v2/health",
}


@pytest.mark.asyncio
async def test_14_routes_registered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

    # 14 routes = sum of methods across the 12 distinct /api/v2 paths.
    route_count = 0
    for path, methods in schema["paths"].items():
        if path.startswith("/api/v2/"):
            route_count += len(methods)
    assert route_count == 14, f"expected 14 routes, got {route_count}"
