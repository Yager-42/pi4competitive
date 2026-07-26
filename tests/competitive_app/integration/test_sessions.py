"""Integration O4/O9/O10/O11 — sessions prompt → JSONL → resume + echo tool + model resolution."""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


async def _client(app_state):
    from competitive_app.adapter.in_.fastapi.app import create_app

    app = create_app()
    app.state.application = app_state  # type: ignore[attr-defined]
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_session_prompt_persists_jsonl_and_returns_assistant_message(app_state, tmp_path: Path):
    from earendil_works.pi_ai.providers.faux import faux_assistant_message

    app_state.models.__faux["setResponses"]([faux_assistant_message("pong")])  # type: ignore[attr-defined]

    async with await _client(app_state) as client:
        create = await client.post("/api/v2/sessions", json={"model": "", "system_prompt": ""})
        assert create.status_code == 200, create.text
        session_id = create.json()["session_id"]

        prompt = await client.post(
            f"/api/v2/sessions/{session_id}/prompt", json={"content": "ping"}
        )
        assert prompt.status_code == 200, prompt.text
        body = prompt.json()
        assert body["session_id"] == session_id
        msg = body["message"]
        assert msg is not None
        assert msg["role"] == "assistant"

        msgs = await client.get(f"/api/v2/sessions/{session_id}/messages")
        assert msgs.status_code == 200
        roles = [m.get("role") for m in msgs.json()["messages"] if isinstance(m, dict)]
        assert roles[0] == "user"
        assert roles[-1] == "assistant"

    # JSONL file landed under data/sessions/--test--/
    sessions_dir = tmp_path / "sessions"
    jsonl_files = list(sessions_dir.rglob("*.jsonl"))
    assert jsonl_files, f"no JSONL file under {sessions_dir}"


@pytest.mark.asyncio
async def test_session_resume_new_instance(app_state, tmp_path: Path):
    """New app instance (same SQLite+JSONL dir) can resume the session."""
    from competitive_app.adapter.in_.fastapi.app import create_app
    from competitive_app.wiring import build_application_state, load_config_from_env
    from earendil_works.pi_ai.providers.faux import faux_assistant_message

    # Instance A: create + prompt
    app_state.models.__faux["setResponses"]([faux_assistant_message("first")])  # type: ignore[attr-defined]
    async with await _client(app_state) as client_a:
        create = await client_a.post("/api/v2/sessions", json={})
        session_id = create.json()["session_id"]
        await client_a.post(f"/api/v2/sessions/{session_id}/prompt", json={"content": "hi"})

    # Instance B: new state, same tmp dirs → resume
    config_b = load_config_from_env()
    state_b = await build_application_state(config_b)
    try:
        state_b.models.__faux["setResponses"]([faux_assistant_message("second")])  # type: ignore[attr-defined]
        app_b = create_app()
        app_b.state.application = state_b  # type: ignore[attr-defined]
        async with AsyncClient(transport=ASGITransport(app=app_b), base_url="http://test") as client_b:
            msgs = await client_b.get(f"/api/v2/sessions/{session_id}/messages")
            assert msgs.status_code == 200, msgs.text
            roles = [m.get("role") for m in msgs.json()["messages"] if isinstance(m, dict)]
            assert "user" in roles and "assistant" in roles

            prompt2 = await client_b.post(
                f"/api/v2/sessions/{session_id}/prompt", json={"content": "again"}
            )
            assert prompt2.status_code == 200, prompt2.text
            assert prompt2.json()["message"]["role"] == "assistant"
    finally:
        await state_b.shutdown()


@pytest.mark.asyncio
async def test_capability_echo_tool_invoked(app_state):
    """echo tool (capability_packages/echo_example) is callable via faux toolCall."""
    from earendil_works.pi_ai.providers.faux import faux_assistant_message, faux_tool_call

    app_state.models.__faux["setResponses"](  # type: ignore[attr-defined]
        [
            faux_assistant_message([faux_tool_call("echo", {"text": "hello"})]),
            faux_assistant_message("done"),
        ]
    )
    async with await _client(app_state) as client:
        create = await client.post("/api/v2/sessions", json={})
        session_id = create.json()["session_id"]
        prompt = await client.post(
            f"/api/v2/sessions/{session_id}/prompt", json={"content": "call echo"}
        )
        assert prompt.status_code == 200, prompt.text
        msgs = (await client.get(f"/api/v2/sessions/{session_id}/messages")).json()["messages"]
        roles = [m.get("role") for m in msgs if isinstance(m, dict)]
        assert "toolResult" in roles, f"echo tool did not produce a toolResult: {roles}"


@pytest.mark.asyncio
async def test_reasonix_prefix_cache_is_active_by_default(app_state):
    runner = app_state.capability_report.extension_runner
    reasonix = next(
        extension
        for extension in runner.extensions
        if "reasonix_prefix_cache" in extension.resolvedPath
    )
    assert set(reasonix.handlers) == {
        "before_provider_request",
        "after_provider_response",
        "message_end",
        "turn_end",
        "session_before_compact",
        "session_compact",
    }
    assert not reasonix.tools


def test_model_resolver_honors_explicit_gateway_for_catalog_id(monkeypatch):
    from competitive_app.wiring import _ModelResolver

    class Models:
        @staticmethod
        def getModels():
            return [{"id": "catalog-model", "baseUrl": "https://api.openai.com/v1"}]

    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example/v1")
    resolved = _ModelResolver(Models(), "catalog-model", allow_synthesize=True).resolve(None)
    assert resolved["baseUrl"] == "https://gateway.example/v1"
    assert resolved["api"] == "openai-completions"


@pytest.mark.asyncio
async def test_model_resolution_unknown_returns_422(app_state):
    async with await _client(app_state) as client:
        resp = await client.post("/api/v2/sessions", json={"model": "does-not-exist"})
        assert resp.status_code == 422, resp.text
