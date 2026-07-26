"""Engine-only extension types.

upstream: packages/coding-agent/src/core/extensions/types.ts
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeAlias, TypedDict

from earendil_works.pi_agent.types import AgentMessage, AgentTool

IN_EVENTS = frozenset({
    "session_start", "session_shutdown", "session_info_changed",
    "session_before_compact", "session_compact", "context",
    "before_provider_request", "before_provider_headers", "after_provider_response",
    "before_agent_start", "agent_start", "agent_end", "agent_settled",
    "turn_start", "turn_end", "message_start", "message_update", "message_end",
    "tool_execution_start", "tool_execution_update", "tool_execution_end",
    "tool_call", "tool_result", "model_select", "thinking_level_select",
})
OUT_EVENTS = frozenset({
    "project_trust", "input", "user_bash", "session_before_switch",
    "session_before_fork", "session_before_tree", "session_tree", "resources_discover",
})

Handler: TypeAlias = Callable[[dict[str, Any], "ExtensionContext"], Any | Awaitable[Any]]
ExtensionFactory: TypeAlias = Callable[["ExtensionAPI"], Any | Awaitable[Any]]

class CompactionPlan(TypedDict):
    version: int
    snapshotFingerprint: str
    foldEntryIds: list[str]
    retainEntryIds: list[str]
    summaryInstructions: str
    details: Any


class SessionBeforeCompactResult(TypedDict, total=False):
    cancel: bool
    compaction: dict[str, Any]
    compactionPlan: CompactionPlan


class ExtensionContext(Protocol):
    cwd: str
    sessionManager: Any
    modelRegistry: Any
    model: Any
    signal: Any

    def abort(self) -> None: ...
    def isIdle(self) -> bool: ...
    def hasPendingMessages(self) -> bool: ...
    def shutdown(self) -> None: ...
    def getContextUsage(self) -> dict[str, Any] | None: ...
    def compact(self, options: dict[str, Any] | None = None) -> Any: ...
    def getSystemPrompt(self) -> str: ...


@dataclass(frozen=True)
class SourceInfo:
    path: str
    source: str = "local"
    baseDir: str | None = None


@dataclass(frozen=True)
class RegisteredTool:
    definition: AgentTool
    sourceInfo: SourceInfo


@dataclass
class Extension:
    path: str
    resolvedPath: str
    sourceInfo: SourceInfo
    handlers: dict[str, list[Handler]] = field(default_factory=dict)
    tools: dict[str, RegisteredTool] = field(default_factory=dict)


@dataclass
class ExtensionRuntime:
    actions: dict[str, Callable[..., Any]] = field(default_factory=dict)
    stale_message: str | None = None

    def assert_active(self) -> None:
        if self.stale_message:
            raise RuntimeError(self.stale_message)

    def invalidate(self, message: str | None = None) -> None:
        self.stale_message = self.stale_message or message or "This extension context is stale"

    def call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        self.assert_active()
        try:
            action = self.actions[name]
        except KeyError as exc:
            raise RuntimeError("Extension runtime not initialized") from exc
        return action(*args, **kwargs)


@dataclass
class LoadExtensionsResult:
    extensions: list[Extension]
    errors: list[dict[str, str]]
    runtime: ExtensionRuntime


class ExtensionAPI:
    def __init__(self, extension: Extension, runtime: ExtensionRuntime) -> None:
        self._extension = extension
        self._runtime = runtime

    def on(self, event: str, handler: Handler) -> None:
        self._runtime.assert_active()
        if event not in IN_EVENTS:
            raise ValueError(f"Unsupported extension event: {event}")
        self._extension.handlers.setdefault(event, []).append(handler)

    def register_tool(self, tool: AgentTool) -> None:
        self._runtime.assert_active()
        if not isinstance(tool, AgentTool):
            raise TypeError(f"register_tool expects AgentTool, got {type(tool)!r}")
        self._extension.tools[tool.name] = RegisteredTool(tool, self._extension.sourceInfo)

    def registerTool(self, tool: AgentTool) -> None:  # noqa: N802
        self.register_tool(tool)


@dataclass
class ExtensionError:
    extensionPath: str
    event: str
    error: str


__all__ = [
    "CompactionPlan", "Extension", "ExtensionAPI", "ExtensionContext", "ExtensionError",
    "ExtensionFactory", "ExtensionRuntime", "Handler", "IN_EVENTS", "LoadExtensionsResult",
    "OUT_EVENTS", "RegisteredTool", "SessionBeforeCompactResult", "SourceInfo",
]
