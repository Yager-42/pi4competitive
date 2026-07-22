"""Auth helpers — envApiKeyAuth, lazyOAuth."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .types import ApiKeyAuth, AuthResult, Credential, OAuthAuth


def env_api_key_auth(name: str, env_vars: list[str] | tuple[str, ...]) -> ApiKeyAuth:
    async def resolve(args: dict[str, Any]) -> AuthResult | None:
        credential = args.get("credential")
        ctx = args["ctx"]
        if credential and credential.get("key"):
            result: AuthResult = {
                "auth": {"apiKey": credential["key"]},
                "source": "stored credential",
            }
            if credential.get("env"):
                result["env"] = credential["env"]
            return result
        for env_var in env_vars:
            value = await ctx.env(env_var)
            if value:
                return {"auth": {"apiKey": value}, "source": env_var}
        return None

    async def login(interaction: Any) -> Credential:
        key = await interaction.prompt({"type": "secret", "message": f"Enter {name}"})
        return {"type": "api_key", "key": key}

    return {"name": name, "login": login, "resolve": resolve}


def lazy_oauth(
    *,
    name: str,
    load: Callable[[], Awaitable[OAuthAuth]],
    login_label: str | None = None,
) -> OAuthAuth:
    cache: dict[str, OAuthAuth] = {}

    async def loaded() -> OAuthAuth:
        if "v" not in cache:
            cache["v"] = await load()
        return cache["v"]

    async def login(interaction: Any) -> Credential:
        return await (await loaded())["login"](interaction)

    async def refresh(credential: Credential, *args: Any) -> Credential:
        impl = await loaded()
        return await impl["refresh"](credential, *args)

    async def to_auth(credential: Credential) -> AuthResult | None:
        impl = await loaded()
        return await impl["toAuth"](credential)

    auth: OAuthAuth = {"name": name, "login": login, "refresh": refresh, "toAuth": to_auth}
    if login_label:
        auth["loginLabel"] = login_label
    return auth
