"""Lazy OAuth loaders — structural parity with upstream auth/oauth/load.ts."""

from __future__ import annotations

from typing import Any

from ..types import AuthResult, Credential, OAuthAuth


async def _unsupported_login(interaction: Any) -> Credential:
    raise NotImplementedError("OAuth login is host-adapted; wire a browser callback for production use")


async def _unsupported_refresh(credential: Credential, *args: Any) -> Credential:
    raise NotImplementedError("OAuth refresh not configured for this host build")


async def _to_auth_from_access(credential: Credential) -> AuthResult | None:
    access = credential.get("access")
    if not access:
        return None
    return {"auth": {"apiKey": str(access)}, "source": "oauth"}


def _stub_oauth(name: str) -> OAuthAuth:
    return {
        "name": name,
        "login": _unsupported_login,
        "refresh": _unsupported_refresh,
        "toAuth": _to_auth_from_access,
    }


async def load_anthropic_oauth() -> OAuthAuth:
    return _stub_oauth("Anthropic (Claude Pro/Max)")


async def load_openrouter_oauth() -> OAuthAuth:
    return _stub_oauth("OpenRouter OAuth")


async def load_xai_oauth() -> OAuthAuth:
    return _stub_oauth("xAI OAuth")


async def load_radius_oauth() -> OAuthAuth:
    return _stub_oauth("Radius OAuth")
