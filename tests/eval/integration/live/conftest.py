"""Conftest for eval live tests (D12).

Reuses tests/live_env.py for env-gating (L2) + creds. Live tests need both a
provider key (OPENAI_API_KEY) and competitive_app running on :8000 — otherwise
they skip. TAVILY_API_KEY gates the search-backed cases (D8).
"""

from __future__ import annotations

import os

import pytest

from tests.live_env import live_credentials, load_dotenv


@pytest.fixture
def live_env(monkeypatch: pytest.MonkeyPatch):
    """Load .env into env; skip if no provider key (L2)."""
    load_dotenv()
    creds = live_credentials()
    if not creds:
        pytest.skip("no OPENAI_API_KEY / MODEL_API_KEY in env or .env (L2)")
    # Wire the real model id + base_url (deepseek-v4-flash etc.).
    monkeypatch.setenv("OPENAI_MODEL", creds["model_id"])
    monkeypatch.setenv("OPENAI_BASE_URL", creds["base_url"])
    # Disable faux; use the real openai provider.
    monkeypatch.delenv("USE_FAUX", raising=False)
    return creds


@pytest.fixture
def tavily_env(live_env):
    """Gate on TAVILY_API_KEY for search-backed live cases (D8)."""
    if not os.environ.get("TAVILY_API_KEY"):
        pytest.skip("no TAVILY_API_KEY in env or .env (D8)")
    return True


@pytest.fixture
def app_running():
    """Skip if competitive_app is not serving on :8000.

    The eval smoke test drives the app over HTTP (A2 variant), so the server
    must be up. Start it in another shell with:
        uv run competitive_app serve --port 8000
    """
    import httpx

    try:
        r = httpx.get("http://127.0.0.1:8000/api/v2/health", timeout=2)
        if r.status_code != 200:
            pytest.skip(
                "competitive_app not healthy on :8000 "
                "(start with: uv run competitive_app serve --port 8000)"
            )
    except httpx.HTTPError:
        pytest.skip(
            "competitive_app not running on :8000 "
            "(start with: uv run competitive_app serve --port 8000)"
        )
    return True
