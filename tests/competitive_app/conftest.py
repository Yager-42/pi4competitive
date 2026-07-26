"""Shared fixtures for competitive_app integration tests.

Builds a FastAPI app backed by faux provider + tmp dirs, and exposes the faux
handle so tests can script model responses (setResponses).
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
async def app_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("USE_FAUX", "1")
    monkeypatch.setenv("SESSIONS_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("APP_DB", str(tmp_path / "app.db"))
    monkeypatch.setenv("SESSIONS_CWD", "test")
    monkeypatch.setenv("CAPABILITY_PACKAGES_ENABLED", "echo_example,reasonix_prefix_cache")
    monkeypatch.setenv("PROMPT_LOCK_TIMEOUT", "2")

    from competitive_app.adapter.in_.fastapi.app import create_app
    from competitive_app.wiring import build_application_state, load_config_from_env

    config = load_config_from_env()
    state = await build_application_state(config)
    app = create_app()
    app.state.application = state  # type: ignore[attr-defined]
    try:
        yield state
    finally:
        await state.shutdown()


@pytest.fixture
def faux(app_state):
    """The faux provider handle (call faux['setResponses']([...]) to script)."""
    return getattr(app_state.models, "_ApplicationState__faux", None) or getattr(
        app_state.models, "__faux", None
    )
