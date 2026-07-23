"""Session repository shared helpers.

upstream: packages/agent/src/harness/session/repo-utils.ts
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, TypeVar

from earendil_works.pi_ai import uuidv7

from ..types import Result, SessionError, SessionTreeEntry, get_or_throw

if TYPE_CHECKING:
    from .session import Session
    from ..types import SessionMetadata, SessionStorage

TValue = TypeVar("TValue")


def create_session_id() -> str:
    return uuidv7()


def create_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def to_session(storage: SessionStorage[Any]) -> Session[Any]:
    from .session import Session

    return Session(storage)


def get_file_system_result_or_throw(result: Result[TValue, Any], message: str) -> TValue:
    if not result["ok"]:
        error = result["error"]
        code = "not_found" if getattr(error, "code", None) == "not_found" else "storage"
        raise SessionError(code, f"{message}: {error}", error if isinstance(error, Exception) else None)
    return result["value"]


async def get_entries_to_fork(
    storage: SessionStorage[Any],
    options: dict[str, Any],
) -> list[SessionTreeEntry]:
    entry_id = options.get("entryId")
    if not entry_id:
        return await storage.getEntries()
    target = await storage.getEntry(entry_id)
    if not target:
        raise SessionError("invalid_fork_target", f"Entry {entry_id} not found")
    position = options.get("position") or "before"
    if position == "at":
        effective_leaf_id: str | None = target["id"]
    else:
        if target.get("type") != "message" or not isinstance(target.get("message"), dict):
            raise SessionError("invalid_fork_target", f"Entry {entry_id} is not a user message")
        if target["message"].get("role") != "user":  # type: ignore[index]
            raise SessionError("invalid_fork_target", f"Entry {entry_id} is not a user message")
        effective_leaf_id = target.get("parentId")  # type: ignore[assignment]
    return await storage.getPathToRootOrCompaction(effective_leaf_id)


__all__ = [
    "create_session_id",
    "create_timestamp",
    "get_entries_to_fork",
    "get_file_system_result_or_throw",
    "get_or_throw",
    "to_session",
]
