"""Auth types — port of auth/types.ts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol, TypedDict

from ..types import ProviderEnv, ProviderHeaders


class ModelAuth(TypedDict, total=False):
    apiKey: str
    headers: ProviderHeaders
    baseUrl: str


class ApiKeyCredential(TypedDict, total=False):
    type: Literal["api_key"]
    key: str
    env: ProviderEnv


class OAuthCredential(TypedDict, total=False):
    type: Literal["oauth"]
    access: str
    refresh: str
    expires: int
    accountId: str
    email: str


Credential = ApiKeyCredential | OAuthCredential
AuthType = Literal["api_key", "oauth"]


class CredentialInfo(TypedDict, total=False):
    type: AuthType
    source: str


class AuthResult(TypedDict, total=False):
    auth: ModelAuth
    source: str
    env: ProviderEnv


class AuthCheck(TypedDict, total=False):
    source: str
    type: AuthType


class AuthContext(Protocol):
    async def env(self, name: str) -> str | None: ...


class AuthInteraction(Protocol):
    async def prompt(self, spec: dict[str, Any]) -> str: ...
    async def emit(self, event: dict[str, Any]) -> None: ...


class ApiKeyAuth(TypedDict, total=False):
    name: str
    login: Callable[[Any], Awaitable[Credential]]
    resolve: Callable[[dict[str, Any]], Awaitable[AuthResult | None]]
    check: Callable[[dict[str, Any]], Awaitable[AuthCheck | None]]


class OAuthAuth(TypedDict, total=False):
    name: str
    loginLabel: str
    login: Callable[[Any], Awaitable[Credential]]
    refresh: Callable[..., Awaitable[Credential]]
    toAuth: Callable[[Credential], Awaitable[AuthResult | None]]


class ProviderAuth(TypedDict, total=False):
    apiKey: ApiKeyAuth
    oauth: OAuthAuth


class CredentialStore(Protocol):
    async def read(self, provider_id: str) -> Credential | None: ...
    async def delete(self, provider_id: str) -> None: ...
    async def modify(
        self,
        provider_id: str,
        mutator: Callable[[Credential | None], Awaitable[Credential | None]],
    ) -> Credential | None: ...
