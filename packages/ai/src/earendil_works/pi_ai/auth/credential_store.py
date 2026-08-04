"""In-memory credential store — port of auth/credential-store.ts."""

from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable
from typing import Any

from .types import Credential


class InMemoryCredentialStore:
    def __init__(self) -> None:
        self._entries: dict[str, Credential] = {}

    async def read(self, provider_id: str) -> Credential | None:
        entry = self._entries.get(provider_id)
        return copy.deepcopy(entry) if entry is not None else None

    async def delete(self, provider_id: str) -> None:
        self._entries.pop(provider_id, None)

    async def modify(
        self,
        provider_id: str,
        mutator: Callable[[Credential | None], Awaitable[Credential | None]],
    ) -> Credential | None:
        current = await self.read(provider_id)
        next_cred = await mutator(current)
        if next_cred is None:
            # ``None`` is the mutator's no-write signal. Use ``delete`` when
            # callers intentionally need to remove a credential.
            return copy.deepcopy(current) if current is not None else None
        if not next_cred:
            raise ValueError("credential must not be empty")
        self._entries[provider_id] = copy.deepcopy(next_cred)
        return copy.deepcopy(next_cred)

    async def write(self, provider_id: str, credential: Credential) -> None:
        if not credential:
            raise ValueError("credential must not be empty")
        self._entries[provider_id] = copy.deepcopy(credential)
