"""Conftest for competitive_app live tests (research-workflow-v1 L1/L2)."""
from __future__ import annotations

import pytest

from tests.live_env import live_credentials, load_dotenv


@pytest.fixture
def live_env(monkeypatch: pytest.MonkeyPatch):
    """Load .env into env; skip if no provider key (L2)."""
    load_dotenv()
    creds = live_credentials()
    if not creds:
        pytest.skip("no OPENAI_API_KEY / MODEL_API_KEY in env or .env (L2)")
    # Wire the real model id as default + base_url.
    monkeypatch.setenv("OPENAI_MODEL", creds["model_id"])
    monkeypatch.setenv("OPENAI_BASE_URL", creds["base_url"])
    # Disable faux; use the real openai provider.
    monkeypatch.delenv("USE_FAUX", raising=False)
    return creds
