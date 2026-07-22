"""Models store — port of models-store.ts."""

from __future__ import annotations

import copy
from typing import Protocol, TypedDict

from .types import Model


class ModelsStoreEntry(TypedDict, total=False):
    models: list[Model]
    lastModified: float
    checkedAt: float


class ModelsStore(Protocol):
    async def read(self, provider_id: str) -> ModelsStoreEntry | None: ...
    async def write(self, provider_id: str, entry: ModelsStoreEntry) -> None: ...
    async def delete(self, provider_id: str) -> None: ...


class InMemoryModelsStore:
    def __init__(self) -> None:
        self._entries: dict[str, ModelsStoreEntry] = {}

    async def read(self, provider_id: str) -> ModelsStoreEntry | None:
        entry = self._entries.get(provider_id)
        return copy.deepcopy(entry) if entry else None

    async def write(self, provider_id: str, entry: ModelsStoreEntry) -> None:
        self._entries[provider_id] = copy.deepcopy(entry)

    async def delete(self, provider_id: str) -> None:
        self._entries.pop(provider_id, None)
