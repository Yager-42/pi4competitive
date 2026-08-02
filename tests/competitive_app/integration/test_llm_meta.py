"""Integration — /llm/ping + /meta diagnostics (batch4 v0.3.4).

ping: one completeSimple round-trip (faux-scripted offline). Verifies
{ok, model, reply, latency_ms} on success and {ok:false, reason, message} on
not_configured / error. meta: shape + no base_url/api_key leak.
"""

from __future__ import annotations

import pytest

from tests.competitive_app.integration.test_workflow import _client


@pytest.mark.asyncio
async def test_llm_ping_ok(app_state, faux):
    from earendil_works.pi_ai.providers.faux import faux_assistant_message

    faux["setResponses"]([faux_assistant_message("pong")])
    async with await _client(app_state) as client:
        body = (await client.get("/api/v2/llm/ping")).json()
    assert body["ok"] is True
    assert body["model"]  # model name present
    assert body["reply"] == "pong"
    assert isinstance(body["latency_ms"], int) and body["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_llm_ping_not_configured(app_state):
    # Flip the configured flag off → ping must short-circuit without calling.
    app_state.task_service._llm_configured = False
    async with await _client(app_state) as client:
        body = (await client.get("/api/v2/llm/ping")).json()
    assert body["ok"] is False
    assert body["reason"] == "not_configured"
    assert "message" in body


@pytest.mark.asyncio
async def test_llm_ping_empty_reply_is_error(app_state, faux):
    from earendil_works.pi_ai.providers.faux import faux_assistant_message

    # Whitespace-only reply strips to empty → reason="error" (empty model reply).
    faux["setResponses"]([faux_assistant_message("   ")])
    async with await _client(app_state) as client:
        body = (await client.get("/api/v2/llm/ping")).json()
    assert body["ok"] is False
    assert body["reason"] == "error"
    assert "message" in body


@pytest.mark.asyncio
async def test_meta_shape_and_no_secret_leak(app_state):
    async with await _client(app_state) as client:
        body = (await client.get("/api/v2/meta")).json()
    assert body["app"] == {"name": "CompetitorLens", "version": "0.1.0"}
    assert body["contract_version"] == "0.3.9"
    assert body["http_feature_version"] == "0.3.4"
    assert body["pi_ai"]
    assert body["pi_agent"]
    # No base_url / api_key values ever leak — llm carries only {configured, model}.
    assert set(body["llm"]) == {"configured", "model"}
    assert body["llm"]["configured"] is True  # faux mode in tests
    assert isinstance(body["capabilities"], list)
    pkgs = {c["package"] for c in body["capabilities"]}
    assert "echo_example" in pkgs  # enabled in conftest app_state
    echo = next(c for c in body["capabilities"] if c["package"] == "echo_example")
    assert echo["tools"] == ["echo"]
    assert body["runtime"] == "pi-agent"
    assert isinstance(body["active_workflows"], int)
