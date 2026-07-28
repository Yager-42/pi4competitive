"""Shared fixtures for competitive_app integration tests.

Builds a FastAPI app backed by faux provider + tmp dirs, and exposes the faux
handle so tests can script model responses (setResponses).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
async def app_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("USE_FAUX", "1")
    monkeypatch.setenv("SESSIONS_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("APP_DB", str(tmp_path / "app.db"))
    monkeypatch.setenv("SESSIONS_CWD", "test")
    monkeypatch.setenv("CAPABILITY_PACKAGES_ENABLED", "echo_example,reasonix_prefix_cache")
    monkeypatch.setenv("PROMPT_LOCK_TIMEOUT", "2")
    # Serial sub-agent dispatch by default so scripted faux responses are
    # consumed deterministically (parallel queue order is nondeterministic).
    # Parallelism is verified in tests/competitive_app/unit/test_socm.py.
    monkeypatch.setenv("SEARCH_MAX_PARALLEL", "1")

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


@pytest.fixture
def mock_fetch_tool(app_state):
    """Register a fake ``test_fetch`` AgentTool returning a page with pricing.

    PR5 judge extraction needs fetched pages to extract from. Real search
    packages need API keys + network; tests inject this offline mock. The tool
    returns a page whose content embeds the entity's price so the (faux) judge
    can extract it. Appended to task_service capability_tools so the coverage
    engine's ``is_search_tool`` picks it up (name ends with ``_fetch``).
    """
    from earendil_works.pi_agent.types import AgentTool

    PRICES = {"acme": "$10/mo", "beta": "$20/mo", "gamma": "$30/mo", "delta": "$40/mo"}

    async def _execute(tool_call_id: str, params: Any, signal=None, on_update=None):
        url = params.get("url", "") if isinstance(params, dict) else ""
        # Pick the price by matching an entity slug in the url.
        price = "$0"
        for slug, p in PRICES.items():
            if slug in url.lower():
                price = p
                break
        page_text = f"Pricing page for {url}. The plan costs {price} per month."
        payload = {"url": url, "content": page_text, "results": [{"url": url, "content": page_text}]}
        return {
            "content": [{"type": "text", "text": page_text}],
            "details": payload,
        }

    tool = AgentTool(
        name="test_fetch",
        description="Offline mock fetch for tests (returns a page with pricing).",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        label="Test Fetch",
        execute=_execute,
        executionMode="parallel",
    )
    app_state.task_service._capability_tools.append(tool)
    yield tool
    app_state.task_service._capability_tools.remove(tool)

