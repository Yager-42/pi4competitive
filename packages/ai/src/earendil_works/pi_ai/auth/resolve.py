"""Auth resolution — port of auth/resolve.ts."""

from __future__ import annotations

import time
from typing import Any, Literal

from ..types import ProviderEnv
from .context import DefaultAuthContext
from .types import (
    ApiKeyAuth,
    AuthContext,
    AuthResult,
    Credential,
    CredentialStore,
    OAuthAuth,
    ProviderAuth,
)

ModelsErrorCode = Literal["model_source", "model_validation", "provider", "stream", "auth", "oauth"]


class ModelsError(Exception):
    def __init__(self, code: ModelsErrorCode, message: str, *, cause: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.cause = cause


async def resolve_provider_auth(
    provider: dict[str, Any] | Any,
    credentials: CredentialStore,
    auth_context: AuthContext,
    overrides: dict[str, Any] | None = None,
) -> AuthResult | None:
    provider_id = provider["id"] if isinstance(provider, dict) else provider.id
    auth: ProviderAuth = provider["auth"] if isinstance(provider, dict) else provider.auth
    overrides = overrides or {}

    # Explicit apiKey override wins
    if overrides.get("apiKey"):
        result: AuthResult = {
            "auth": {"apiKey": overrides["apiKey"]},
            "source": "request",
        }
        if overrides.get("env"):
            result["env"] = overrides["env"]
        return result

    ctx = auth_context
    if overrides.get("env"):
        ctx = _overlay_env(auth_context, overrides["env"])

    stored = await _read_credential(credentials, provider_id)

    if stored and stored.get("type") == "oauth":
        oauth = auth.get("oauth")
        if not oauth:
            return None
        return await _resolve_stored_oauth(credentials, provider_id, oauth, stored)

    api_key = auth.get("apiKey")
    if not api_key:
        return None
    cred = stored if stored and stored.get("type") == "api_key" else None
    return await _resolve_api_key(ctx, api_key, provider_id, cred)


def _overlay_env(base: AuthContext, env: ProviderEnv) -> AuthContext:
    async def env_fn(name: str) -> str | None:
        if name in env and env[name]:
            return env[name]
        return await base.env(name)

    class Overlay:
        async def env(self, name: str) -> str | None:
            return await env_fn(name)

    return Overlay()


async def _resolve_stored_oauth(
    credentials: CredentialStore,
    provider_id: str,
    oauth: OAuthAuth,
    stored: Credential,
) -> AuthResult | None:
    try:
        expires = int(stored.get("expires") or 0)
        if time.time() * 1000 < expires:
            return await oauth["toAuth"](stored)
        # refresh
        async def mutator(current: Credential | None) -> Credential | None:
            if current is None or current.get("type") != "oauth":
                return current
            if time.time() * 1000 < int(current.get("expires") or 0):
                return current  # another task refreshed it; do not overwrite
            return await oauth["refresh"](current)

        post = await credentials.modify(provider_id, mutator)
        use = post if post and post.get("type") == "oauth" else stored
        return await oauth["toAuth"](use)
    except Exception as exc:
        raise ModelsError("auth", f"OAuth resolution failed for {provider_id}", cause=exc) from exc


async def _resolve_api_key(
    auth_context: AuthContext,
    api_key: ApiKeyAuth,
    provider_id: str,
    credential: Credential | None,
) -> AuthResult | None:
    try:
        return await api_key["resolve"]({"ctx": auth_context, "credential": credential})
    except Exception as exc:
        raise ModelsError("auth", f"API key resolution failed for {provider_id}", cause=exc) from exc


async def _read_credential(credentials: CredentialStore, provider_id: str) -> Credential | None:
    try:
        return await credentials.read(provider_id)
    except Exception as exc:
        raise ModelsError("auth", f"Credential store read failed for {provider_id}", cause=exc) from exc
