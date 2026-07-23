"""Harness config/types (session + result/errors).

upstream: packages/agent/src/harness/types.ts
"""
from __future__ import annotations

from typing import Any, Generic, Literal, NotRequired, Protocol, TypedDict, TypeVar

from earendil_works.pi_agent.types import AgentMessage

TValue = TypeVar("TValue")
TError = TypeVar("TError")
TMetadata = TypeVar("TMetadata", bound="SessionMetadata")


class Ok(TypedDict, Generic[TValue]):
    ok: Literal[True]
    value: TValue


class Err(TypedDict, Generic[TError]):
    ok: Literal[False]
    error: TError


Result = Ok[TValue] | Err[TError]


def ok(value: TValue) -> Ok[TValue]:
    return {"ok": True, "value": value}


def err(error: TError) -> Err[TError]:
    return {"ok": False, "error": error}


def get_or_throw(result: Result[TValue, TError]) -> TValue:
    if not result["ok"]:
        raise result["error"]  # type: ignore[misc]
    return result["value"]


def to_error(error: Any) -> Exception:
    if isinstance(error, Exception):
        return error
    if isinstance(error, str):
        return Exception(error)
    try:
        import json

        return Exception(json.dumps(error))
    except Exception:
        return Exception(str(error))


class FileError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        path: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.name = "FileError"
        self.code = code
        self.path = path
        self.__cause__ = cause


class SessionError(Exception):
    def __init__(self, code: str, message: str, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.name = "SessionError"
        self.code = code
        self.__cause__ = cause


class SessionTreeEntryBase(TypedDict):
    type: str
    id: str
    parentId: str | None
    timestamp: str


class MessageEntry(SessionTreeEntryBase):
    type: Literal["message"]  # type: ignore[misc]
    message: AgentMessage


class ThinkingLevelChangeEntry(SessionTreeEntryBase):
    type: Literal["thinking_level_change"]  # type: ignore[misc]
    thinkingLevel: str


class ModelChangeEntry(SessionTreeEntryBase):
    type: Literal["model_change"]  # type: ignore[misc]
    provider: str
    modelId: str


class ActiveToolsChangeEntry(SessionTreeEntryBase):
    type: Literal["active_tools_change"]  # type: ignore[misc]
    activeToolNames: list[str]


class CompactionEntry(SessionTreeEntryBase, total=False):
    type: Literal["compaction"]  # type: ignore[misc]
    summary: str
    tokensBefore: int
    firstKeptEntryId: str
    retainedTail: list[AgentMessage]
    details: Any
    usage: dict[str, Any]
    fromHook: bool


class BranchSummaryEntry(SessionTreeEntryBase, total=False):
    type: Literal["branch_summary"]  # type: ignore[misc]
    fromId: str
    summary: str
    details: Any
    usage: dict[str, Any]
    fromHook: bool


class CustomEntry(SessionTreeEntryBase, total=False):
    type: Literal["custom"]  # type: ignore[misc]
    customType: str
    data: Any


class CustomMessageEntry(SessionTreeEntryBase, total=False):
    type: Literal["custom_message"]  # type: ignore[misc]
    customType: str
    content: Any
    display: bool
    details: Any


class LabelEntry(SessionTreeEntryBase, total=False):
    type: Literal["label"]  # type: ignore[misc]
    targetId: str
    label: str | None


class SessionInfoEntry(SessionTreeEntryBase, total=False):
    type: Literal["session_info"]  # type: ignore[misc]
    name: str


class LeafEntry(SessionTreeEntryBase):
    type: Literal["leaf"]  # type: ignore[misc]
    targetId: str | None


SessionTreeEntry = (
    MessageEntry
    | ThinkingLevelChangeEntry
    | ModelChangeEntry
    | ActiveToolsChangeEntry
    | CompactionEntry
    | BranchSummaryEntry
    | CustomEntry
    | CustomMessageEntry
    | LabelEntry
    | SessionInfoEntry
    | LeafEntry
)


class SessionContext(TypedDict):
    messages: list[AgentMessage]
    thinkingLevel: str
    model: dict[str, str] | None
    activeToolNames: list[str] | None


class SessionStats(TypedDict):
    messageCount: int
    cachedTokens: int
    uncachedTokens: int
    totalTokens: int
    costTotal: float


class SessionMetadata(TypedDict):
    id: str
    createdAt: str


class JsonlSessionMetadata(SessionMetadata, total=False):
    cwd: str
    path: str
    parentSessionPath: str
    metadata: dict[str, Any]


class SessionEntryCursorOptions(TypedDict, total=False):
    afterEntrySeq: int
    limit: int


class SessionStorage(Protocol[TMetadata]):
    async def getMetadata(self) -> TMetadata: ...
    async def getLeafId(self) -> str | None: ...
    async def setLeafId(self, leaf_id: str | None) -> None: ...
    async def createEntryId(self) -> str: ...
    async def appendEntry(self, entry: SessionTreeEntry) -> None: ...
    async def getEntry(self, id: str) -> SessionTreeEntry | None: ...
    async def findEntries(self, type: str) -> list[SessionTreeEntry]: ...
    async def getLabel(self, id: str) -> str | None: ...
    async def getSessionName(self) -> str | None: ...
    async def getSessionStats(self) -> SessionStats: ...
    async def getPathToRootOrCompaction(self, leaf_id: str | None) -> list[SessionTreeEntry]: ...
    async def getEntries(self, options: SessionEntryCursorOptions | None = None) -> list[SessionTreeEntry]: ...


class FileInfo(TypedDict):
    name: str
    path: str
    kind: Literal["file", "directory", "symlink"]
    size: int
    mtimeMs: float


__all__ = [
    "ActiveToolsChangeEntry",
    "BranchSummaryEntry",
    "CompactionEntry",
    "CustomEntry",
    "CustomMessageEntry",
    "FileError",
    "FileInfo",
    "JsonlSessionMetadata",
    "LabelEntry",
    "LeafEntry",
    "MessageEntry",
    "ModelChangeEntry",
    "Result",
    "SessionContext",
    "SessionEntryCursorOptions",
    "SessionError",
    "SessionInfoEntry",
    "SessionMetadata",
    "SessionStats",
    "SessionStorage",
    "SessionTreeEntry",
    "SessionTreeEntryBase",
    "ThinkingLevelChangeEntry",
    "err",
    "get_or_throw",
    "ok",
    "to_error",
]
