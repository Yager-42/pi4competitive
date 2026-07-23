"""In-memory session storage (tests).

upstream: packages/agent/src/harness/session/memory-storage.ts
"""
from __future__ import annotations

from typing import Any

from earendil_works.pi_ai import uuidv7

from ..types import (
    LeafEntry,
    SessionEntryCursorOptions,
    SessionError,
    SessionMetadata,
    SessionStats,
    SessionTreeEntry,
)


def _update_label_cache(labels_by_id: dict[str, str], entry: SessionTreeEntry) -> None:
    if entry.get("type") != "label":
        return
    label = (entry.get("label") or "").strip()  # type: ignore[union-attr]
    target = entry.get("targetId")  # type: ignore[assignment]
    if not isinstance(target, str):
        return
    if label:
        labels_by_id[target] = label
    else:
        labels_by_id.pop(target, None)


def _build_labels(entries: list[SessionTreeEntry]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for entry in entries:
        _update_label_cache(labels, entry)
    return labels


def generate_entry_id(by_id: dict[str, SessionTreeEntry]) -> str:
    for _ in range(100):
        entry_id = uuidv7()[-8:]
        if entry_id not in by_id:
            return entry_id
    return uuidv7()


def leaf_id_after_entry(entry: SessionTreeEntry) -> str | None:
    if entry.get("type") == "leaf":
        return entry.get("targetId")  # type: ignore[return-value]
    return entry.get("id")  # type: ignore[return-value]


class InMemorySessionStorage:
    def __init__(
        self,
        options: dict[str, Any] | None = None,
    ) -> None:
        options = options or {}
        entries = list(options.get("entries") or [])
        self._entries: list[SessionTreeEntry] = entries
        self._by_id: dict[str, SessionTreeEntry] = {e["id"]: e for e in entries}
        self._labels_by_id = _build_labels(entries)
        self._leaf_id: str | None = None
        for entry in self._entries:
            self._leaf_id = leaf_id_after_entry(entry)
        if self._leaf_id is not None and self._leaf_id not in self._by_id:
            raise SessionError("invalid_session", f"Entry {self._leaf_id} not found")
        meta = options.get("metadata")
        if meta is None:
            from .repo_utils import create_session_id, create_timestamp

            meta = {"id": create_session_id(), "createdAt": create_timestamp()}
        self._metadata: SessionMetadata = meta

    async def getMetadata(self) -> SessionMetadata:
        return self._metadata

    async def getLeafId(self) -> str | None:
        if self._leaf_id is not None and self._leaf_id not in self._by_id:
            raise SessionError("invalid_session", f"Entry {self._leaf_id} not found")
        return self._leaf_id

    async def setLeafId(self, leaf_id: str | None) -> None:
        if leaf_id is not None and leaf_id not in self._by_id:
            raise SessionError("not_found", f"Entry {leaf_id} not found")
        from .repo_utils import create_timestamp

        entry: LeafEntry = {
            "type": "leaf",
            "id": generate_entry_id(self._by_id),
            "parentId": self._leaf_id,
            "timestamp": create_timestamp(),
            "targetId": leaf_id,
        }
        self._entries.append(entry)
        self._by_id[entry["id"]] = entry
        self._leaf_id = leaf_id

    async def createEntryId(self) -> str:
        return generate_entry_id(self._by_id)

    async def appendEntry(self, entry: SessionTreeEntry) -> None:
        self._entries.append(entry)
        self._by_id[entry["id"]] = entry
        _update_label_cache(self._labels_by_id, entry)
        self._leaf_id = leaf_id_after_entry(entry)

    async def getEntry(self, id: str) -> SessionTreeEntry | None:
        return self._by_id.get(id)

    async def findEntries(self, type: str) -> list[SessionTreeEntry]:
        return [e for e in self._entries if e.get("type") == type]

    async def getLabel(self, id: str) -> str | None:
        return self._labels_by_id.get(id)

    async def getSessionName(self) -> str | None:
        entries = await self.findEntries("session_info")
        if not entries:
            return None
        name = (entries[-1].get("name") or "").strip()  # type: ignore[union-attr]
        return name or None

    async def getSessionStats(self) -> SessionStats:
        message_count = 0
        cached = 0
        uncached = 0
        total = 0
        cost_total = 0.0
        for entry in self._entries:
            if entry.get("type") == "message":
                message_count += 1
            usage = None
            if entry.get("type") == "message":
                msg = entry.get("message")
                if isinstance(msg, dict) and msg.get("role") == "assistant":
                    usage = msg.get("usage")
            elif entry.get("type") in ("compaction", "branch_summary"):
                usage = entry.get("usage")
            if not isinstance(usage, dict):
                continue
            try:
                inp = int(usage["input"])
                out = int(usage["output"])
                cr = int(usage["cacheRead"])
                cw = int(usage["cacheWrite"])
                cost = float(usage["cost"]["total"])
            except Exception:
                continue
            cached += cr
            uncached += inp + cw
            total += inp + out + cr + cw
            cost_total += cost
        return {
            "messageCount": message_count,
            "cachedTokens": cached,
            "uncachedTokens": uncached,
            "totalTokens": total,
            "costTotal": cost_total,
        }

    async def getPathToRootOrCompaction(self, leaf_id: str | None) -> list[SessionTreeEntry]:
        if leaf_id is None:
            return []
        path: list[SessionTreeEntry] = []
        stop_at: str | None = None
        current = self._by_id.get(leaf_id)
        if not current:
            raise SessionError("not_found", f"Entry {leaf_id} not found")
        while current:
            path.insert(0, current)
            if stop_at is not None and current["id"] == stop_at:
                break
            if current.get("type") == "compaction":
                if current.get("retainedTail"):
                    break
                stop_at = current.get("firstKeptEntryId")  # type: ignore[assignment]
            parent_id = current.get("parentId")
            if not parent_id:
                break
            parent = self._by_id.get(parent_id)
            if not parent:
                raise SessionError("invalid_session", f"Entry {parent_id} not found")
            current = parent
        return path

    async def getEntries(
        self, options: SessionEntryCursorOptions | None = None
    ) -> list[SessionTreeEntry]:
        start = (options or {}).get("afterEntrySeq") or 0
        limit = (options or {}).get("limit")
        if limit is None:
            return list(self._entries[start:])
        return list(self._entries[start : start + limit])


__all__ = ["InMemorySessionStorage", "generate_entry_id", "leaf_id_after_entry"]
