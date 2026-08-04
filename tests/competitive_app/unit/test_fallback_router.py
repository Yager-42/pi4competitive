"""FallbackRouter tests — poirot test_model_router.py 行为断言语义平移。

Transplant source: HezaoHezao/poirot
Path: poirot/backend/tests/v1/unit/config/test_model_router.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see native/vendor/licenses/POIROT-MIT.txt)
ADAPT (plan §3 阶段 3): 角色路由断言 → env 链断言; ProviderConfig 构造 → pi 工厂注册表。
"""

from __future__ import annotations

import pytest
import asyncio

from competitive_app.application.model.fallback_stream import FallbackStream
from competitive_app.application.model.router import (
    PROVIDER_REGISTRY,
    ProviderConfig,
    ProviderConfigError,
    build_fallback_chain,
    chain_model_from_config,
    discover_available_providers,
    parse_provider_env,
    resolve_provider_config,
)

from types import SimpleNamespace


def _pc(name: str) -> ProviderConfig:
    return ProviderConfig(
        provider=name,
        model="m",
        api_key="k",
        base_url="http://x",
        priority=1,
        default=False,
        enabled=True,
    )


# --- env 链构造（route_chain_for 语义：按序筛 + 不可用跳过 + 空链 raise）---

def test_chain_preserves_env_order() -> None:
    prov = [_pc("openai"), _pc("qwen"), _pc("deepseek")]
    chain = build_fallback_chain(["openai", "qwen", "deepseek"], prov)
    assert [p.provider for p in chain] == ["openai", "qwen", "deepseek"]


def test_chain_skips_unavailable_names() -> None:
    prov = [_pc("openai"), _pc("deepseek")]
    chain = build_fallback_chain(["openai", "qwen", "deepseek"], prov)
    assert [p.provider for p in chain] == ["openai", "deepseek"]


def test_empty_chain_raises() -> None:
    with pytest.raises(ProviderConfigError):
        build_fallback_chain(["openai"], [])


def test_parse_provider_env_comma_separated() -> None:
    assert parse_provider_env(" openai, ,opencode ") == ["openai", "opencode"]
    assert parse_provider_env(None) == []
    assert parse_provider_env("") == []


# --- discover_available_providers（enabled + key 判定 + priority 排序）---

def test_discover_filters_no_key_and_sorts_by_priority() -> None:
    no_key = ProviderConfig(
        provider="no-key", model="m", api_key="", base_url=None, priority=0, default=False, enabled=True
    )
    low = ProviderConfig(
        provider="low", model="m", api_key="k", base_url=None, priority=5, default=False, enabled=True
    )
    high = ProviderConfig(
        provider="high", model="m", api_key="k", base_url=None, priority=1, default=False, enabled=True
    )
    disabled = ProviderConfig(
        provider="disabled", model="m", api_key="k", base_url=None, priority=0, default=False, enabled=False
    )
    available = discover_available_providers([no_key, low, high, disabled])
    assert [p.provider for p in available] == ["high", "low"]


# --- pi 工厂注册表（ADAPT ②/③）---

def test_resolve_provider_config_requires_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert resolve_provider_config("openai", priority=0) is None
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    config = resolve_provider_config("openai", priority=0, default=True)
    assert config is not None
    assert config.provider == "openai"
    assert config.api_key == "sk-test"
    assert config.default is True
    config.require_api_key()  # 不抛


def test_resolve_provider_config_no_key_provider() -> None:
    # openai-codex: ambient auth，无需 key
    config = resolve_provider_config("openai-codex", priority=0)
    assert config is not None
    assert config.provider == "openai-codex"


def test_resolve_unknown_provider_returns_none() -> None:
    assert resolve_provider_config("not-a-provider", priority=0) is None


def test_chain_model_from_config_gateway_openai(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example/v1")
    config = ProviderConfig(
        provider="openai", model="glm-5.2", api_key="k",
        base_url="https://api.openai.com/v1", priority=0, default=True, enabled=True,
    )
    model = chain_model_from_config(config)
    assert model["provider"] == "openai"
    assert model["baseUrl"] == "https://gateway.example/v1"
    assert model["id"] == "glm-5.2"


def test_chain_model_from_config_factory_base_url(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    config = ProviderConfig(
        provider="opencode", model="m", api_key="k",
        base_url="https://opencode.example", priority=0, default=False, enabled=True,
    )
    model = chain_model_from_config(config)
    assert model["provider"] == "opencode"
    assert model["baseUrl"] == "https://opencode.example"

def test_discover_includes_ambient_provider_without_api_key() -> None:
    config = resolve_provider_config("openai-codex", priority=0)
    assert config is not None
    assert config.api_key == ""
    assert config.requires_api_key is False
    assert discover_available_providers([config]) == [config]


def test_resolve_empty_catalog_is_unavailable(monkeypatch) -> None:
    monkeypatch.setitem(
        PROVIDER_REGISTRY,
        "empty-catalog",
        (lambda: SimpleNamespace(getModels=lambda: [], baseUrl="https://example.test"), ()),
    )
    assert resolve_provider_config("empty-catalog", priority=0) is None

def test_resolve_catalog_without_model_id_is_unavailable(monkeypatch) -> None:
    monkeypatch.setitem(
        PROVIDER_REGISTRY,
        "invalid-catalog",
        (lambda: SimpleNamespace(getModels=lambda: [{"api": "openai-responses"}], baseUrl=None), ()),
    )
    assert resolve_provider_config("invalid-catalog", priority=0) is None


def test_resolve_and_chain_model_preserve_catalog_protocol(monkeypatch) -> None:
    monkeypatch.setitem(
        PROVIDER_REGISTRY,
        "responses-provider",
        (
            lambda: SimpleNamespace(
                getModels=lambda: [
                    {
                        "id": "response-model",
                        "name": "Response Model",
                        "api": "openai-responses",
                        "reasoning": True,
                        "input": ["text"],
                        "contextWindow": 42,
                        "maxTokens": 7,
                    }
                ],

                baseUrl="https://example.test",
            ),
            (),
        ),
    )
    config = resolve_provider_config("responses-provider", priority=0)
    assert config is not None
    model = chain_model_from_config(config)
    assert config.api == "openai-responses"
    assert model["api"] == "openai-responses"
    assert model["name"] == "Response Model"
    assert model["reasoning"] is True
    assert model["contextWindow"] == 42
    assert model["maxTokens"] == 7

@pytest.mark.asyncio
async def test_fallback_timeout_error_tracks_last_provider() -> None:
    calls: list[str] = []
    journal: list[tuple[str, dict]] = []

    class _NeverDelegate:
        def streamSimple(self, model, context, options=None):
            calls.append(model["provider"])

            async def never():
                await asyncio.Event().wait()
                yield {}  # pragma: no cover

            return never()

    def model(provider: str) -> dict:
        return {
            "id": f"m-{provider}",
            "name": provider,
            "api": "openai-completions",
            "provider": provider,
        }

    first = model("first")
    second = model("second")
    stream = FallbackStream(
        _NeverDelegate(),
        chain=[first, second],
        first_packet_timeout_ms=1,
        emit_fallback_event=lambda event_type, payload: journal.append((event_type, payload)),
    )(first, {"messages": []})
    result = await stream.result()

    assert calls == ["first", "second"]
    assert result["provider"] == "second"
    assert result["error"]["type"] == "timeout"
    exhausted = next(payload for event, payload in journal if event == "llm.fallback_exhausted")
    assert exhausted["lastProvider"] == "second"
