"""FallbackRouter tests — poirot test_model_router.py 行为断言语义平移。

Transplant source: HezaoHezao/poirot
Path: poirot/backend/tests/v1/unit/config/test_model_router.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see native/vendor/licenses/POIROT-MIT.txt)
ADAPT (plan §3 阶段 3): 角色路由断言 → env 链断言; ProviderConfig 构造 → pi 工厂注册表。
"""

from __future__ import annotations

import pytest
from competitive_app.application.model.router import (
    ProviderConfig,
    ProviderConfigError,
    build_fallback_chain,
    chain_model_from_config,
    discover_available_providers,
    parse_provider_env,
    resolve_provider_config,
)


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
