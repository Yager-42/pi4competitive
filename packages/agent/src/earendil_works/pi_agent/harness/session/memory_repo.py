"""In-memory session repository.

upstream: packages/agent/src/harness/session/memory-repo.ts
"""
from __future__ import annotations

from typing import Any

from ..types import SessionError, SessionMetadata
from .memory_storage import InMemorySessionStorage
from .repo_utils import create_session_id, create_timestamp, get_entries_to_fork, to_session
from .session import Session


class InMemorySessionRepo:
    def __init__(self) -> None:
        self._sessions: dict[str, Session[SessionMetadata]] = {}

    async def create(self, options: dict[str, Any] | None = None) -> Session[SessionMetadata]:
        options = options or {}
        metadata: SessionMetadata = {
            "id": options.get("id") or create_session_id(),
            "createdAt": create_timestamp(),
        }
        storage = InMemorySessionStorage({"metadata": metadata})
        session = to_session(storage)
        self._sessions[metadata["id"]] = session
        return session

    async def open(self, metadata: SessionMetadata) -> Session[SessionMetadata]:
        session = self._sessions.get(metadata["id"])
        if not session:
            raise SessionError("not_found", f"Session not found: {metadata['id']}")
        return session

    async def list(self, options: Any = None) -> list[SessionMetadata]:
        out: list[SessionMetadata] = []
        for session in self._sessions.values():
            out.append(await session.get_metadata())
        return out

    async def delete(self, metadata: SessionMetadata) -> None:
        self._sessions.pop(metadata["id"], None)

    async def fork(
        self,
        source_metadata: SessionMetadata,
        options: dict[str, Any] | None = None,
    ) -> Session[SessionMetadata]:
        options = options or {}
        source = await self.open(source_metadata)
        forked_entries = await get_entries_to_fork(source.get_storage(), options)
        metadata: SessionMetadata = {
            "id": options.get("id") or create_session_id(),
            "createdAt": create_timestamp(),
        }
        storage = InMemorySessionStorage({"metadata": metadata, "entries": forked_entries})
        session = to_session(storage)
        self._sessions[metadata["id"]] = session
        return session


__all__ = ["InMemorySessionRepo"]
