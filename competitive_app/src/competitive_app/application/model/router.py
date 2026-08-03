"""Fallback provider chain resolution.

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/config/provider_config.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see native/vendor/licenses/POIROT-MIT.txt)

COPY: ``ProviderConfigError`` / ``ProviderConfig`` / ``discover_available_providers``
(enabled+key 判定 + priority 排序) verbatim; ``route_chain_for`` structure
(name-order filtering + empty-chain raise) retained.

ADAPT (plan P4-llm-fallback-observability §2 阶段 3, listed points only):
  1. ``route_chain_for(role, ...)`` → ``build_fallback_chain(provider_names, ...)``
     — MODEL_ROUTES 角色表 → ``LLM_FALLBACK_PROVIDERS`` env 链 (G4); deepseek
     tail-append dropped (no default provider in a single global chain).
  2. ``PROVIDER_PROFILES`` 静态表 → pi provider 工厂注册表 (``PROVIDER_REGISTRY``).
  3. ``build_chat_model`` (LangChain 构造) → ``chain_model_from_config``
     (pi Model dict: factory catalog model + baseUrl resolution).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from earendil_works.pi_ai.models import Provider
    from earendil_works.pi_ai.types import Model

    ProviderFactory = Callable[[], Provider]
else:
    ProviderFactory = Callable[[], Any]


class ProviderConfigError(ValueError):
    """Raised when model provider config is missing or invalid."""


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    api_key: str
    base_url: str | None
    priority: int
    default: bool
    enabled: bool
    window: int = 0  # 上下文窗口（token），0=未知

    def require_api_key(self) -> str:
        if not self.api_key:
            raise ProviderConfigError(f"api_key is empty for provider: {self.provider}")
        return self.api_key


def parse_provider_env(value: str | None) -> list[str]:
    """``LLM_FALLBACK_PROVIDERS`` → 按序 provider 名列表（逗号分隔，空项忽略）。"""
    if not value:
        return []
    return [name.strip() for name in value.split(",") if name.strip()]


def discover_available_providers(configs: list[ProviderConfig]) -> list[ProviderConfig]:
    """返回 enabled 且 api_key 非空的 provider（no_key_required 的除外）。按 priority 升序。"""
    available = [c for c in configs if c.enabled and c.api_key]
    return sorted(available, key=lambda p: p.priority)


def build_fallback_chain(
    provider_names: list[str],
    providers: list[ProviderConfig],
) -> list[ProviderConfig]:
    """按 env 链顺序筛 provider；链空抛 ProviderConfigError。

    COPY ``route_chain_for`` 语义：名字不在可用集 → 跳过；空链 → raise。
    ADAPT：角色路由表 → env 链输入（G4），无兜底追加。
    """
    by_name = {p.provider: p for p in providers}
    chain = [by_name[name] for name in provider_names if name in by_name]
    if not chain:
        raise ProviderConfigError(f"no available provider for chain: {provider_names}")
    return chain


# ---------------------------------------------------------------------------
# pi provider 工厂注册表（ADAPT ②：poirot PROVIDER_PROFILES → pi 工厂）
# 第二元素 = 该 provider 的 api key env 变量（空元组 = 无需 key，如 ambient auth）。
# ---------------------------------------------------------------------------
def _lazy_import(module: str, attr: str) -> Callable[[], Any]:
    def factory() -> Any:
        import importlib

        return getattr(importlib.import_module(module), attr)()

    return factory


PROVIDER_REGISTRY: dict[str, tuple[ProviderFactory, tuple[str, ...]]] = {
    "openai": (
        _lazy_import("earendil_works.pi_ai.providers.openai", "openai_provider"),
        ("OPENAI_API_KEY",),
    ),
    "openai-codex": (
        _lazy_import("earendil_works.pi_ai.providers.openai_codex", "openai_codex_provider"),
        (),  # ambient auth：无 key 要求
    ),
    "opencode": (
        _lazy_import("earendil_works.pi_ai.providers.opencode", "opencode_provider"),
        ("OPENCODE_API_KEY",),
    ),
    "opencode-go": (
        _lazy_import("earendil_works.pi_ai.providers.opencode_go", "opencode_go_provider"),
        ("OPENCODE_API_KEY",),
    ),
    "nvidia": (
        _lazy_import("earendil_works.pi_ai.providers.nvidia", "nvidia_provider"),
        ("NVIDIA_API_KEY",),
    ),
}


def resolve_provider_config(
    name: str,
    *,
    priority: int,
    default: bool = False,
    env_lookup: Callable[[str], str | None] = os.environ.get,
) -> ProviderConfig | None:
    """pi 工厂 → ProviderConfig（无 key 且需 key 的 provider → None = 不可用）。"""
    entry = PROVIDER_REGISTRY.get(name)
    if entry is None:
        return None
    factory, env_keys = entry
    api_key = ""
    for key in env_keys:
        value = env_lookup(key)
        if value:
            api_key = value
            break
    if not api_key and env_keys:
        return None
    provider = factory()
    models = provider.getModels() or []
    model_id = models[0]["id"] if models else ""
    return ProviderConfig(
        provider=name,
        model=model_id,
        api_key=api_key,
        base_url=provider.baseUrl,
        priority=priority,
        default=default,
        enabled=True,
        window=0,
    )


def chain_model_from_config(config: ProviderConfig) -> Model:
    """ProviderConfig → pi Model dict（ADAPT ③：build_chat_model 的 pi 版）。

    - ``openai`` 且设了 ``OPENAI_BASE_URL`` → 网关 baseUrl（与 _ModelResolver
      显式网关规则一致，避免链头打到 api.openai.com）。
    - 其余 provider → 工厂 catalog 首模型 + 工厂 baseUrl。
    """
    if config.provider == "openai" and os.environ.get("OPENAI_BASE_URL"):
        base_url = os.environ["OPENAI_BASE_URL"]
    else:
        base_url = config.base_url or "https://api.openai.com/v1"
    return {
        "id": config.model,
        "name": config.model,
        "api": "openai-completions",
        "provider": config.provider,
        "baseUrl": base_url,
        "reasoning": False,
        "input": ["text", "image"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 128000,
        "maxTokens": 8192,
    }


__all__ = [
    "PROVIDER_REGISTRY",
    "ProviderConfig",
    "ProviderConfigError",
    "build_fallback_chain",
    "chain_model_from_config",
    "discover_available_providers",
    "parse_provider_env",
    "resolve_provider_config",
]
