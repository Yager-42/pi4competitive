"""Application model layer: multi-LLM fallback (router + stream) + journal stream."""

from competitive_app.application.model.fallback_stream import (
    DEFAULT_FIRST_PACKET_TIMEOUT_MS,
    FallbackStream,
    _should_fallback,
)
from competitive_app.application.model.journal_stream import JournalStream
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

__all__ = [
    "DEFAULT_FIRST_PACKET_TIMEOUT_MS",
    "PROVIDER_REGISTRY",
    "FallbackStream",
    "JournalStream",
    "ProviderConfig",
    "ProviderConfigError",
    "_should_fallback",
    "build_fallback_chain",
    "chain_model_from_config",
    "discover_available_providers",
    "parse_provider_env",
    "resolve_provider_config",
]
