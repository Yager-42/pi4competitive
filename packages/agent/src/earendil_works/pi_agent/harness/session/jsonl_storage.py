"""JSONL append/read session storage.

upstream: packages/agent/src/harness/session/jsonl-storage.ts
"""
from __future__ import annotations

import json
import math
from typing import Any, Protocol

from ..types import (
    JsonlSessionMetadata,
    LeafEntry,
    Result,
    SessionEntryCursorOptions,
    SessionError,
    SessionStats,
    SessionTreeEntry,
    to_error,
)
from .memory_storage import (
    generate_entry_id,
    leaf_id_after_entry,
    _build_labels,
    _update_label_cache,
)
from .repo_utils import create_timestamp, get_file_system_result_or_throw


class JsonlSessionStorageFileSystem(Protocol):
    async def readTextFile(self, path: str, abort_signal: Any = None) -> Result[str, Any]: ...
    async def readTextLines(
        self, path: str, options: dict[str, Any] | None = None, abort_signal: Any = None
    ) -> Result[list[str], Any]: ...
    async def writeFile(self, path: str, content: str, abort_signal: Any = None) -> Result[None, Any]: ...
    async def appendFile(self, path: str, content: str, abort_signal: Any = None) -> Result[None, Any]: ...


def _invalid_session(file_path: str, message: str, cause: Exception | None = None) -> SessionError:
    return SessionError("invalid_session", f"Invalid JSONL session file {file_path}: {message}", cause)


def _invalid_entry(
    file_path: str, line_number: int, message: str, cause: Exception | None = None
) -> SessionError:
    return SessionError(
        "invalid_entry",
        f"Invalid JSONL session file {file_path}: line {line_number} {message}",
        cause,
    )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def parse_header_line(line: str, file_path: str) -> dict[str, Any]:
    try:
        parsed = json.loads(line, parse_constant=_reject_json_constant)
    except Exception as error:
        raise _invalid_session(file_path, "first line is not a valid session header", to_error(error)) from error
    if not isinstance(parsed, dict):
        raise _invalid_session(file_path, "first line is not a valid session header")
    if parsed.get("type") != "session":
        raise _invalid_session(file_path, "first line is not a valid session header")
    if parsed.get("version") != 3:
        raise _invalid_session(file_path, "unsupported session version")
    if not isinstance(parsed.get("id"), str) or not parsed["id"]:
        raise _invalid_session(file_path, "session header is missing id")
    if not isinstance(parsed.get("timestamp"), str) or not parsed["timestamp"]:
        raise _invalid_session(file_path, "session header is missing timestamp")
    if not isinstance(parsed.get("cwd"), str) or not parsed["cwd"]:
        raise _invalid_session(file_path, "session header is missing cwd")
    if "parentSession" in parsed and parsed["parentSession"] is not None and not isinstance(
        parsed["parentSession"], str
    ):
        raise _invalid_session(file_path, "session header parentSession must be a string")
    if "metadata" in parsed and parsed["metadata"] is not None:
        if not isinstance(parsed["metadata"], dict):
            raise _invalid_session(file_path, "session header metadata must be an object")
    return {
        "type": "session",
        "version": 3,
        "id": parsed["id"],
        "timestamp": parsed["timestamp"],
        "cwd": parsed["cwd"],
        "parentSession": parsed.get("parentSession"),
        "metadata": parsed.get("metadata"),
    }


def _is_json_safe(value: Any) -> bool:
    if value is None or isinstance(value, (str, int, bool)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_json_safe(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_safe(item) for key, item in value.items())
    return False


def _validate_entry_fields(parsed: dict[str, Any]) -> None:
    entry_type = parsed["type"]
    known_types = {
        "message", "thinking_level_change", "model_change", "active_tools_change",
        "compaction", "branch_summary", "custom", "custom_message", "label",
        "session_info", "leaf",
    }
    if entry_type not in known_types:
        raise ValueError(f"has unknown entry type {entry_type!r}")

    def require(name: str, expected: type | tuple[type, ...]) -> Any:
        value = parsed.get(name)
        if not isinstance(value, expected):
            raise ValueError(f"has invalid {name}")
        return value

    if entry_type == "message":
        message = require("message", dict)
        role = message.get("role")
        if role not in {"user", "assistant", "toolResult"}:
            raise ValueError("has invalid message role")
        content = message.get("content")
        if isinstance(content, str):
            if role == "user":
                return
            raise ValueError("has invalid message content")
        if not isinstance(content, list):
            raise ValueError("has invalid message content")
        allowed = {"text", "image"} if role in {"user", "toolResult"} else {"text", "thinking", "toolCall"}
        for block in content:
            if not isinstance(block, dict) or block.get("type") not in allowed:
                raise ValueError("has invalid message content block")
            block_type = block["type"]
            if block_type == "text":
                if not isinstance(block.get("text"), str):
                    raise ValueError("has invalid text content block")
            elif block_type == "thinking":
                if not isinstance(block.get("thinking"), str):
                    raise ValueError("has invalid thinking content block")
                if "redacted" in block and not isinstance(block["redacted"], bool):
                    raise ValueError("has invalid thinking content block")
            elif block_type == "image":
                if not isinstance(block.get("data"), str) or not isinstance(block.get("mimeType"), str):
                    raise ValueError("has invalid image content block")
            elif block_type == "toolCall":
                if not isinstance(block.get("id"), str) or not block["id"]:
                    raise ValueError("has invalid tool call content block")
                if not isinstance(block.get("name"), str) or not block["name"]:
                    raise ValueError("has invalid tool call content block")
                if not isinstance(block.get("arguments"), dict) or not _is_json_safe(block["arguments"]):
                    raise ValueError("has invalid tool call content block")
    elif entry_type == "thinking_level_change":
        require("thinkingLevel", str)
    elif entry_type == "model_change":
        require("provider", str)
        require("modelId", str)
    elif entry_type == "active_tools_change":
        names = require("activeToolNames", list)
        if not all(isinstance(name, str) for name in names):
            raise ValueError("has invalid activeToolNames")
    elif entry_type == "compaction":
        require("summary", str)
        tokens = require("tokensBefore", int)
        if isinstance(tokens, bool):
            raise ValueError("has invalid tokensBefore")
        if "firstKeptEntryId" in parsed and parsed["firstKeptEntryId"] is not None:
            require("firstKeptEntryId", str)
        if "retainedTail" in parsed:
            tail = require("retainedTail", list)
            if not all(isinstance(message, dict) for message in tail):
                raise ValueError("has invalid retainedTail")
        if "usage" in parsed and parsed["usage"] is not None:
            require("usage", dict)
        if "fromHook" in parsed and not isinstance(parsed["fromHook"], bool):
            raise ValueError("has invalid fromHook")
    elif entry_type == "branch_summary":
        require("fromId", str)
        require("summary", str)
        if "usage" in parsed and parsed["usage"] is not None:
            require("usage", dict)
        if "fromHook" in parsed and not isinstance(parsed["fromHook"], bool):
            raise ValueError("has invalid fromHook")
    elif entry_type == "custom":
        require("customType", str)
    elif entry_type == "custom_message":
        require("customType", str)
        content = parsed.get("content")
        if not isinstance(content, (str, list, dict)) or not _is_json_safe(content):
            raise ValueError("has invalid content")
        if not isinstance(parsed.get("display"), bool):
            raise ValueError("has invalid display")
    elif entry_type == "label":
        require("targetId", str)
        if "label" in parsed and parsed["label"] is not None:
            require("label", str)
    elif entry_type == "session_info":
        require("name", str)
    elif entry_type == "leaf":
        if parsed.get("targetId") is not None:
            require("targetId", str)


def parse_entry_line(line: str, file_path: str, line_number: int) -> SessionTreeEntry:
    try:
        parsed = json.loads(line, parse_constant=_reject_json_constant)
    except Exception as error:
        raise _invalid_entry(file_path, line_number, "is not valid JSON", to_error(error)) from error
    if not isinstance(parsed, dict):
        raise _invalid_entry(file_path, line_number, "is not a valid session entry")
    if not isinstance(parsed.get("type"), str):
        raise _invalid_entry(file_path, line_number, "is missing entry type")
    if not isinstance(parsed.get("id"), str) or not parsed["id"]:
        raise _invalid_entry(file_path, line_number, "is missing entry id")
    if parsed.get("parentId") is not None and not isinstance(parsed.get("parentId"), str):
        raise _invalid_entry(file_path, line_number, "has invalid parentId")
    if not isinstance(parsed.get("timestamp"), str) or not parsed["timestamp"]:
        raise _invalid_entry(file_path, line_number, "is missing timestamp")
    try:
        _validate_entry_fields(parsed)
    except ValueError as error:
        raise _invalid_entry(file_path, line_number, str(error)) from error
    return parsed  # type: ignore[return-value]


def header_to_session_metadata(header: dict[str, Any], path: str) -> JsonlSessionMetadata:
    meta: JsonlSessionMetadata = {
        "id": header["id"],
        "createdAt": header["timestamp"],
        "cwd": header["cwd"],
        "path": path,
    }
    if header.get("parentSession"):
        meta["parentSessionPath"] = header["parentSession"]
    if header.get("metadata") is not None:
        meta["metadata"] = header["metadata"]
    return meta


async def load_jsonl_session_metadata(
    fs: JsonlSessionStorageFileSystem, file_path: str
) -> JsonlSessionMetadata:
    lines = get_file_system_result_or_throw(
        await fs.readTextLines(file_path, {"maxLines": 1}),
        f"Failed to read session header {file_path}",
    )
    line = lines[0] if lines else None
    if line and line.strip():
        return header_to_session_metadata(parse_header_line(line, file_path), file_path)
    raise _invalid_session(file_path, "missing session header")


async def _load_jsonl_storage(
    fs: JsonlSessionStorageFileSystem, file_path: str
) -> dict[str, Any]:
    content = get_file_system_result_or_throw(
        await fs.readTextFile(file_path), f"Failed to read session {file_path}"
    )
    lines = [ln for ln in content.split("\n") if ln.strip()]
    if not lines:
        raise _invalid_session(file_path, "missing session header")
    header = parse_header_line(lines[0], file_path)
    entries: list[SessionTreeEntry] = []
    leaf_id: str | None = None
    for i in range(1, len(lines)):
        entry = parse_entry_line(lines[i], file_path, i + 1)
        entries.append(entry)
        leaf_id = leaf_id_after_entry(entry)
    return {"header": header, "entries": entries, "leafId": leaf_id}


class JsonlSessionStorage:
    def __init__(
        self,
        fs: JsonlSessionStorageFileSystem,
        file_path: str,
        header: dict[str, Any],
        entries: list[SessionTreeEntry],
        leaf_id: str | None,
    ) -> None:
        self._fs = fs
        self._file_path = file_path
        self._metadata = header_to_session_metadata(header, file_path)
        self._entries = list(entries)
        self._by_id: dict[str, SessionTreeEntry] = {e["id"]: e for e in entries}
        self._labels_by_id = _build_labels(entries)
        self._current_leaf_id = leaf_id

    @classmethod
    async def open(cls, fs: JsonlSessionStorageFileSystem, file_path: str) -> JsonlSessionStorage:
        loaded = await _load_jsonl_storage(fs, file_path)
        return cls(fs, file_path, loaded["header"], loaded["entries"], loaded["leafId"])

    @classmethod
    async def create(
        cls,
        fs: JsonlSessionStorageFileSystem,
        file_path: str,
        options: dict[str, Any],
    ) -> JsonlSessionStorage:
        header = {
            "type": "session",
            "version": 3,
            "id": options["sessionId"],
            "timestamp": create_timestamp(),
            "cwd": options["cwd"],
            "parentSession": options.get("parentSessionPath"),
            "metadata": options.get("metadata"),
        }
        # Drop Nones for cleaner JSON
        header = {k: v for k, v in header.items() if v is not None or k in ("type", "version", "id", "timestamp", "cwd")}
        get_file_system_result_or_throw(
            await fs.writeFile(file_path, json.dumps(header) + "\n"),
            f"Failed to create session {file_path}",
        )
        return cls(fs, file_path, header, [], None)

    async def getMetadata(self) -> JsonlSessionMetadata:
        return self._metadata

    async def getLeafId(self) -> str | None:
        if self._current_leaf_id is not None and self._current_leaf_id not in self._by_id:
            raise SessionError("invalid_session", f"Entry {self._current_leaf_id} not found")
        return self._current_leaf_id

    async def setLeafId(self, leaf_id: str | None) -> None:
        if leaf_id is not None and leaf_id not in self._by_id:
            raise SessionError("not_found", f"Entry {leaf_id} not found")
        entry: LeafEntry = {
            "type": "leaf",
            "id": generate_entry_id(self._by_id),
            "parentId": self._current_leaf_id,
            "timestamp": create_timestamp(),
            "targetId": leaf_id,
        }
        get_file_system_result_or_throw(
            await self._fs.appendFile(self._file_path, json.dumps(entry) + "\n"),
            f"Failed to append session leaf {entry['id']}",
        )
        self._entries.append(entry)
        self._by_id[entry["id"]] = entry
        self._current_leaf_id = leaf_id

    async def createEntryId(self) -> str:
        return generate_entry_id(self._by_id)

    async def appendEntry(self, entry: SessionTreeEntry) -> None:
        get_file_system_result_or_throw(
            await self._fs.appendFile(self._file_path, json.dumps(entry) + "\n"),
            f"Failed to append session entry {entry['id']}",
        )
        self._entries.append(entry)
        self._by_id[entry["id"]] = entry
        _update_label_cache(self._labels_by_id, entry)
        self._current_leaf_id = leaf_id_after_entry(entry)

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
        # Same accounting as memory storage
        from .memory_storage import InMemorySessionStorage

        tmp = InMemorySessionStorage({"entries": self._entries, "metadata": self._metadata})
        return await tmp.getSessionStats()

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


__all__ = [
    "JsonlSessionStorage",
    "load_jsonl_session_metadata",
    "parse_header_line",
    "parse_entry_line",
]
