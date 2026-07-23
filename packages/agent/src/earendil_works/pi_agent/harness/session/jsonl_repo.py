"""JSONL session repository.

upstream: packages/agent/src/harness/session/jsonl-repo.ts
"""
from __future__ import annotations

import re
from typing import Any, Protocol

from ..types import JsonlSessionMetadata, Result, SessionError, to_error
from .jsonl_storage import JsonlSessionStorage, load_jsonl_session_metadata
from .repo_utils import (
    create_session_id,
    create_timestamp,
    get_entries_to_fork,
    get_file_system_result_or_throw,
    to_session,
)
from .session import Session


class JsonlSessionRepoFileSystem(Protocol):
    cwd: str

    async def absolutePath(self, path: str, abort_signal: Any = None) -> Result[str, Any]: ...
    async def joinPath(self, parts: list[str], abort_signal: Any = None) -> Result[str, Any]: ...
    async def readTextFile(self, path: str, abort_signal: Any = None) -> Result[str, Any]: ...
    async def readTextLines(
        self, path: str, options: dict[str, Any] | None = None, abort_signal: Any = None
    ) -> Result[list[str], Any]: ...
    async def writeFile(self, path: str, content: str, abort_signal: Any = None) -> Result[None, Any]: ...
    async def appendFile(self, path: str, content: str, abort_signal: Any = None) -> Result[None, Any]: ...
    async def listDir(self, path: str, abort_signal: Any = None) -> Result[list[Any], Any]: ...
    async def exists(self, path: str, abort_signal: Any = None) -> Result[bool, Any]: ...
    async def createDir(
        self, path: str, options: dict[str, Any] | None = None, abort_signal: Any = None
    ) -> Result[None, Any]: ...
    async def remove(
        self, path: str, options: dict[str, Any] | None = None, abort_signal: Any = None
    ) -> Result[None, Any]: ...


def encode_cwd(cwd: str) -> str:
    cleaned = re.sub(r"^[/\\]+", "", cwd)
    cleaned = re.sub(r"[/\\:]", "-", cleaned)
    return f"--{cleaned}--"


class JsonlSessionRepo:
    def __init__(self, options: dict[str, Any]) -> None:
        self._fs: JsonlSessionRepoFileSystem = options["fs"]
        self._sessions_root_input: str = options["sessionsRoot"]
        self._sessions_root: str | None = None

    async def _get_sessions_root(self) -> str:
        if self._sessions_root is None:
            self._sessions_root = get_file_system_result_or_throw(
                await self._fs.absolutePath(self._sessions_root_input),
                f"Failed to resolve sessions root {self._sessions_root_input}",
            )
        return self._sessions_root

    async def _get_session_dir(self, cwd: str) -> str:
        return get_file_system_result_or_throw(
            await self._fs.joinPath([await self._get_sessions_root(), encode_cwd(cwd)]),
            f"Failed to resolve session directory for {cwd}",
        )

    async def _create_session_file_path(self, cwd: str, session_id: str, timestamp: str) -> str:
        safe_ts = re.sub(r"[:.]", "-", timestamp)
        return get_file_system_result_or_throw(
            await self._fs.joinPath(
                [await self._get_session_dir(cwd), f"{safe_ts}_{session_id}.jsonl"]
            ),
            f"Failed to resolve session file path for {session_id}",
        )

    async def create(self, options: dict[str, Any]) -> Session[JsonlSessionMetadata]:
        session_id = options.get("id") or create_session_id()
        created_at = create_timestamp()
        session_dir = await self._get_session_dir(options["cwd"])
        get_file_system_result_or_throw(
            await self._fs.createDir(session_dir, {"recursive": True}),
            f"Failed to create session directory {session_dir}",
        )
        file_path = await self._create_session_file_path(options["cwd"], session_id, created_at)
        storage = await JsonlSessionStorage.create(
            self._fs,
            file_path,
            {
                "cwd": options["cwd"],
                "sessionId": session_id,
                "parentSessionPath": options.get("parentSessionPath"),
                "metadata": options.get("metadata"),
            },
        )
        return to_session(storage)

    async def open(self, metadata: JsonlSessionMetadata) -> Session[JsonlSessionMetadata]:
        path = metadata["path"]
        exists = get_file_system_result_or_throw(
            await self._fs.exists(path), f"Failed to check session {path}"
        )
        if not exists:
            raise SessionError("not_found", f"Session not found: {path}")
        storage = await JsonlSessionStorage.open(self._fs, path)
        return to_session(storage)

    async def list(self, options: dict[str, Any] | None = None) -> list[JsonlSessionMetadata]:
        options = options or {}
        if options.get("cwd"):
            dirs = [await self._get_session_dir(options["cwd"])]
        else:
            dirs = await self._list_session_dirs()
        sessions: list[JsonlSessionMetadata] = []
        for directory in dirs:
            if not get_file_system_result_or_throw(
                await self._fs.exists(directory), f"Failed to check session directory {directory}"
            ):
                continue
            files = get_file_system_result_or_throw(
                await self._fs.listDir(directory), f"Failed to list sessions in {directory}"
            )
            files = [f for f in files if f.get("kind") != "directory" and str(f.get("name", "")).endswith(".jsonl")]
            for file in files:
                try:
                    sessions.append(await load_jsonl_session_metadata(self._fs, file["path"]))
                except Exception as error:
                    cause = to_error(error)
                    if isinstance(cause, SessionError) and cause.code == "invalid_session":
                        continue
                    raise cause from error
        sessions.sort(key=lambda s: s["createdAt"], reverse=True)
        return sessions

    async def delete(self, metadata: JsonlSessionMetadata) -> None:
        get_file_system_result_or_throw(
            await self._fs.remove(metadata["path"], {"force": True}),
            f"Failed to delete session {metadata['path']}",
        )

    async def fork(
        self,
        source_metadata: JsonlSessionMetadata,
        options: dict[str, Any],
    ) -> Session[JsonlSessionMetadata]:
        source = await self.open(source_metadata)
        forked_entries = await get_entries_to_fork(source.get_storage(), options)
        session_id = options.get("id") or create_session_id()
        created_at = create_timestamp()
        session_dir = await self._get_session_dir(options["cwd"])
        get_file_system_result_or_throw(
            await self._fs.createDir(session_dir, {"recursive": True}),
            f"Failed to create session directory {session_dir}",
        )
        storage = await JsonlSessionStorage.create(
            self._fs,
            await self._create_session_file_path(options["cwd"], session_id, created_at),
            {
                "cwd": options["cwd"],
                "sessionId": session_id,
                "parentSessionPath": options.get("parentSessionPath") or source_metadata.get("path"),
                "metadata": options.get("metadata") or source_metadata.get("metadata"),
            },
        )
        for entry in forked_entries:
            await storage.appendEntry(entry)
        return to_session(storage)

    async def _list_session_dirs(self) -> list[str]:
        sessions_root = await self._get_sessions_root()
        if not get_file_system_result_or_throw(
            await self._fs.exists(sessions_root),
            f"Failed to check sessions root {sessions_root}",
        ):
            return []
        entries = get_file_system_result_or_throw(
            await self._fs.listDir(sessions_root),
            f"Failed to list sessions root {sessions_root}",
        )
        return [e["path"] for e in entries if e.get("kind") == "directory"]


__all__ = ["JsonlSessionRepo", "encode_cwd"]
