"""Focused regressions for capability known issues 61-64 and 208-212."""
from __future__ import annotations

import asyncio
import contextvars
import sys
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
for capability in ("search_anysearch", "search_tavily"):
    path = str(ROOT / "capability_packages" / capability / "extensions")
    if path not in sys.path:
        sys.path.insert(0, path)

import anysearch_tools  # noqa: E402
import tavily_tools  # noqa: E402
from pi_auto_review import policy  # noqa: E402
from pi_auto_review import reviewer  # noqa: E402
_register_spec = importlib.util.spec_from_file_location(
    "pi_auto_review_register",
    ROOT / "capability_packages" / "pi_auto_review" / "extensions" / "register.py",
)
assert _register_spec and _register_spec.loader
register = importlib.util.module_from_spec(_register_spec)
_register_spec.loader.exec_module(register)


def test_tool_arguments_are_redacted_before_classifier_transcript() -> None:
    transcript = policy.build_classifier_transcript(
        [
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "name": "http",
                            "arguments": {"api_key": "sk-super-secret-value"},
                        }
                    ],
                }
            }
        ],
        {
            "maxUserTranscriptTokens": 100,
            "maxToolTranscriptTokens": 100,
            "maxRelevantResultTokens": 100,
        },
    )
    assert "super-secret" not in transcript["text"]
    assert "[REDACTED TOKEN]" in transcript["text"]



def test_long_tool_private_key_is_redacted_before_evidence_bound() -> None:
    private_key = "x" * 2200 + "SECRET-PRIVATE-KEY" + "y" * 2200
    transcript = policy.build_classifier_transcript(
        [{"message": {"role": "assistant", "content": [{"type": "toolCall", "name": "write", "arguments": {"key": "-----BEGIN PRIVATE KEY-----\n" + private_key + "\n-----END PRIVATE KEY-----"}}]}}],
        {"maxUserTranscriptTokens": 100, "maxToolTranscriptTokens": 100, "maxRelevantResultTokens": 100},
    )
    assert "SECRET-PRIVATE-KEY" not in transcript["text"]
    assert "[REDACTED PRIVATE KEY]" in transcript["text"]

def test_sandbox_trap_fields_are_markup_escaped() -> None:
    transcript = policy.build_classifier_transcript(
        [],
        {
            "maxUserTranscriptTokens": 100,
            "maxToolTranscriptTokens": 100,
            "maxRelevantResultTokens": 100,
        },
        {"source": "sandbox-runtime", "path": "<img>&"},
    )
    assert "&lt;img&gt;&amp;" in transcript["text"]
    assert "<img>" not in transcript["text"]


def test_provider_qualified_model_requires_matching_provider() -> None:
    class Registry:
        async def getAvailable(self):
            return [
                {"provider": "wrong", "id": "wrong", "name": "wrong"},
                {"provider": "right", "id": "same", "name": "right"},
            ]

        async def getAuth(self, model):
            assert model["provider"] == "right"
            return {"auth": {"apiKey": "key"}}

    config = {"model": "right/same"}
    runtime = asyncio.run(reviewer.resolve_reviewer(Registry(), config))
    assert runtime["model"]["provider"] == "right"
    assert runtime["model"]["id"] == "same"


def test_complete_passes_session_id_to_model_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    async def fake_resolve(registry, config, session_id="pi-auto-review"):
        captured["session_id"] = session_id
        return {"model": {"provider": "p", "id": "m"}, "auth": {}, "sessionId": session_id}

    monkeypatch.setattr(reviewer, "resolve_reviewer", fake_resolve)
    monkeypatch.setattr(reviewer, "_model_call", lambda *args: asyncio.sleep(0, result='{"outcome":"deny","risk_level":"low","user_authorization":"unknown","rationale":"no"}'))
    config = {
        "model": "p/m", "reasoning": "off", "timeoutMs": 1000, "maxTokens": 10,
        "retries": 0, "maxUserTranscriptTokens": 10, "maxToolTranscriptTokens": 10,
        "maxRelevantResultTokens": 10, "failureMode": "deny", "grantTtlMs": 100,
        "autoConfirmBoundedAllows": (),
    }
    result = asyncio.run(reviewer.complete(object(), config, {}, [], "session-42", None))
    assert result.decision["outcome"] == "deny"
    assert captured["session_id"] == "session-42"


def test_async_session_context_fails_closed_without_snapshot_provider() -> None:
    async def build_context():
        return {"messages": [{"role": "user", "content": "secret"}]}

    ctx = SimpleNamespace(sessionManager=SimpleNamespace(build_context=build_context))
    with pytest.raises(RuntimeError, match="async session context"):
        register._entries(ctx)


def test_runtime_binding_cleanup_restores_previous_context() -> None:
    register._unbind_runtime()
    cleanup = register.bind_runtime(model_registry="first")
    try:
        assert register._registry() == "first"
    finally:
        cleanup()
    with pytest.raises(ValueError, match="not bound"):
        register._registry()


def test_stale_runtime_cleanup_cannot_clear_new_or_foreign_binding() -> None:
    register._unbind_runtime()
    old_cleanup = register.bind_runtime(model_registry="old")
    new_cleanup = register.bind_runtime(model_registry="new")
    old_cleanup()
    assert register._registry() == "new"
    contextvars.copy_context().run(new_cleanup)
    assert register._registry() == "new"
    new_cleanup()
    assert register._registry() == "old"
    old_cleanup()
    with pytest.raises(ValueError, match="not bound"):
        register._registry()


def test_fetch_validators_require_http_or_https() -> None:
    for validate in (anysearch_tools._validate_fetch_params, tavily_tools._validate_fetch_params):
        with pytest.raises((anysearch_tools.ProviderError, tavily_tools.ProviderError)):
            validate({"url": "file:///etc/passwd"})
        assert validate({"url": "https://example.com/page"}) == "https://example.com/page"


def test_tavily_post_does_not_follow_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, bool] = {}

    class Client:
        def __init__(self, **kwargs):
            observed["follow_redirects"] = kwargs["follow_redirects"]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return httpx.Response(200, json={"results": []})

    monkeypatch.setattr(tavily_tools.httpx, "AsyncClient", Client)
    asyncio.run(tavily_tools._post_json("/search", {}, api_key="secret", signal=None))
    assert observed["follow_redirects"] is False
