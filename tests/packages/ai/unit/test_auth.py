from __future__ import annotations

import os

import pytest

from earendil_works.pi_ai.auth.context import default_auth_context
from earendil_works.pi_ai.auth.credential_store import InMemoryCredentialStore
from earendil_works.pi_ai.auth.helpers import env_api_key_auth
from earendil_works.pi_ai.auth.resolve import resolve_provider_auth
from earendil_works.pi_ai.models import create_provider
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api


@pytest.mark.asyncio
async def test_api_key_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "from-env")
    auth = env_api_key_auth("Test", ["TEST_PROVIDER_KEY"])
    provider = create_provider(
        {
            "id": "testprov",
            "auth": {"apiKey": auth},
            "models": [],
            "api": open_ai_completions_api(),
        }
    )
    store = InMemoryCredentialStore()
    ctx = default_auth_context()

    # env
    r1 = await resolve_provider_auth(provider, store, ctx)
    assert r1 and r1["auth"]["apiKey"] == "from-env"
    assert r1["source"] == "TEST_PROVIDER_KEY"

    # stored wins over env
    await store.write("testprov", {"type": "api_key", "key": "from-store"})
    r2 = await resolve_provider_auth(provider, store, ctx)
    assert r2 and r2["auth"]["apiKey"] == "from-store"
    assert r2["source"] == "stored credential"

    # request override
    r3 = await resolve_provider_auth(provider, store, ctx, {"apiKey": "from-request"})
    assert r3 and r3["auth"]["apiKey"] == "from-request"
    assert r3["source"] == "request"


@pytest.mark.asyncio
async def test_missing_key_error_is_structured() -> None:
    from earendil_works.pi_ai import ModelsError, create_models
    from earendil_works.pi_ai.providers.deepseek import deepseek_provider

    models = create_models()
    models.setProvider(deepseek_provider())
    model = models.getModels("deepseek")[0]
    # ensure no key
    os.environ.pop("DEEPSEEK_API_KEY", None)
    stream = models.stream(model, {"messages": []})
    events = [e async for e in stream]
    assert events[-1]["type"] == "error"
    msg = await stream.result()
    assert msg["stopReason"] == "error"
    assert msg.get("errorMessage")
