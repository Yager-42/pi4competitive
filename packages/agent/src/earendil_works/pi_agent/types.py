"""Agent core types.

upstream: packages/agent/src/types.ts
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, NotRequired, Protocol, TypedDict, TypeAlias

from earendil_works.pi_ai.types import (
    AssistantMessage,
    AssistantMessageEvent,
    ImageContent,
    Message,
    Model,
    ModelThinkingLevel,
    SimpleStreamOptions,
    TextContent,
    Tool,
    ToolCall,
    ToolResultMessage,
    Usage,
)
from earendil_works.pi_ai.utils.event_stream import AssistantMessageEventStream

# ---------------------------------------------------------------------------
# StreamFn
# ---------------------------------------------------------------------------

StreamFn: TypeAlias = Callable[
    [Model, Mapping[str, Any], SimpleStreamOptions | None],
    AssistantMessageEventStream | Awaitable[AssistantMessageEventStream],
]
"""Stream function used by the agent loop. ``Models.streamSimple`` satisfies this.

Contract:
- Must not throw/reject for request/model/runtime failures.
- Must return an ``AssistantMessageEventStream``.
- Failures encoded via stream events + final AssistantMessage stopReason error/aborted.
"""

ToolExecutionMode = Literal["sequential", "parallel"]
QueueMode = Literal["all", "one-at-a-time"]

# Upstream ThinkingLevel includes xhigh/max; pi_ai ModelThinkingLevel is the same family.
ThinkingLevel = ModelThinkingLevel | Literal["xhigh", "max"]

AgentToolCall: TypeAlias = ToolCall


class BeforeToolCallResult(TypedDict, total=False):
    block: bool
    reason: str


class AfterToolCallResult(TypedDict, total=False):
    content: list[TextContent | ImageContent]
    details: Any
    isError: bool
    usage: Usage
    terminate: bool


class AgentContext(TypedDict):
    systemPrompt: str
    messages: list[AgentMessage]
    tools: NotRequired[list[AgentTool]]


class BeforeToolCallContext(TypedDict):
    assistantMessage: AssistantMessage
    toolCall: AgentToolCall
    args: Any
    context: AgentContext


class AfterToolCallContext(TypedDict):
    assistantMessage: AssistantMessage
    toolCall: AgentToolCall
    args: Any
    result: AgentToolResult
    isError: bool
    context: AgentContext


class ShouldStopAfterTurnContext(TypedDict):
    message: AssistantMessage
    toolResults: list[ToolResultMessage]
    context: AgentContext
    newMessages: list[AgentMessage]


class AgentLoopTurnUpdate(TypedDict, total=False):
    context: AgentContext
    model: Model
    thinkingLevel: ThinkingLevel


PrepareNextTurnContext = ShouldStopAfterTurnContext


class AgentToolResult(TypedDict, total=False):
    """Final or partial result produced by a tool.

    ``content`` and ``details`` are required at finalization; partial updates may omit.
    """

    content: list[TextContent | ImageContent]
    details: Any
    usage: Usage
    addedToolNames: list[str]
    terminate: bool


AgentToolUpdateCallback: TypeAlias = Callable[[AgentToolResult], None]


@dataclass
class AgentTool:
    """Tool definition used by the agent runtime.

    Extends pi_ai ``Tool`` (name/description/parameters) with execute + label.
    TypeBox schemas map to JSON Schema ``parameters`` dicts (Pydantic validation later).
    """

    name: str
    description: str
    parameters: dict[str, Any]
    label: str
    execute: Callable[
        ...,
        Awaitable[AgentToolResult],
    ]
    # (toolCallId, params, signal?, onUpdate?) -> AgentToolResult
    prepareArguments: Callable[[Any], Any] | None = None
    executionMode: ToolExecutionMode | None = None

    def to_llm_tool(self) -> Tool:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


# AgentMessage = LLM Message | custom app messages (extensible)
# Python: custom messages are plain Mapping with at least a role key.
CustomAgentMessage: TypeAlias = Mapping[str, Any]
AgentMessage: TypeAlias = Message | CustomAgentMessage


class AgentEventAgentStart(TypedDict):
    type: Literal["agent_start"]


class AgentEventAgentEnd(TypedDict):
    type: Literal["agent_end"]
    messages: list[AgentMessage]


class AgentEventTurnStart(TypedDict):
    type: Literal["turn_start"]


class AgentEventTurnEnd(TypedDict):
    type: Literal["turn_end"]
    message: AgentMessage
    toolResults: list[ToolResultMessage]


class AgentEventMessageStart(TypedDict):
    type: Literal["message_start"]
    message: AgentMessage


class AgentEventMessageUpdate(TypedDict):
    type: Literal["message_update"]
    message: AgentMessage
    assistantMessageEvent: AssistantMessageEvent


class AgentEventMessageEnd(TypedDict):
    type: Literal["message_end"]
    message: AgentMessage


class AgentEventToolExecutionStart(TypedDict):
    type: Literal["tool_execution_start"]
    toolCallId: str
    toolName: str
    args: Any


class AgentEventToolExecutionUpdate(TypedDict):
    type: Literal["tool_execution_update"]
    toolCallId: str
    toolName: str
    args: Any
    partialResult: Any


class AgentEventToolExecutionEnd(TypedDict):
    type: Literal["tool_execution_end"]
    toolCallId: str
    toolName: str
    result: Any
    isError: bool


AgentEvent = (
    AgentEventAgentStart
    | AgentEventAgentEnd
    | AgentEventTurnStart
    | AgentEventTurnEnd
    | AgentEventMessageStart
    | AgentEventMessageUpdate
    | AgentEventMessageEnd
    | AgentEventToolExecutionStart
    | AgentEventToolExecutionUpdate
    | AgentEventToolExecutionEnd
)


class AgentState(Protocol):
    """Public agent state surface (implemented by Agent).

    ``tools`` / ``messages`` use copy-on-assign semantics in the Agent class.
    """

    systemPrompt: str
    model: Model
    thinkingLevel: ThinkingLevel

    @property
    def tools(self) -> list[AgentTool]: ...

    @tools.setter
    def tools(self, tools: list[AgentTool]) -> None: ...

    @property
    def messages(self) -> list[AgentMessage]: ...

    @messages.setter
    def messages(self, messages: list[AgentMessage]) -> None: ...

    @property
    def isStreaming(self) -> bool: ...

    @property
    def streamingMessage(self) -> AgentMessage | None: ...

    @property
    def pendingToolCalls(self) -> frozenset[str]: ...

    @property
    def errorMessage(self) -> str | None: ...


@dataclass
class AgentLoopConfig:
    """Loop configuration. Stream option fields mirror SimpleStreamOptions (optional).

    Required: model + convertToLlm.
    """

    model: Model
    convertToLlm: Callable[
        [list[AgentMessage]],
        list[Message] | Awaitable[list[Message]],
    ]
    transformContext: (
        Callable[[list[AgentMessage], Any | None], Awaitable[list[AgentMessage]]] | None
    ) = None
    getApiKey: Callable[[str], Awaitable[str | None] | str | None] | None = None
    shouldStopAfterTurn: (
        Callable[[ShouldStopAfterTurnContext], bool | Awaitable[bool]] | None
    ) = None
    prepareNextTurn: (
        Callable[
            [PrepareNextTurnContext],
            AgentLoopTurnUpdate | None | Awaitable[AgentLoopTurnUpdate | None],
        ]
        | None
    ) = None
    getSteeringMessages: Callable[[], Awaitable[list[AgentMessage]]] | None = None
    getFollowUpMessages: Callable[[], Awaitable[list[AgentMessage]]] | None = None
    toolExecution: ToolExecutionMode = "parallel"
    beforeToolCall: (
        Callable[
            [BeforeToolCallContext, Any | None],
            Awaitable[BeforeToolCallResult | None],
        ]
        | None
    ) = None
    afterToolCall: (
        Callable[
            [AfterToolCallContext, Any | None],
            Awaitable[AfterToolCallResult | None],
        ]
        | None
    ) = None
    # SimpleStreamOptions fields (optional)
    temperature: float | None = None
    maxTokens: int | None = None
    signal: Any | None = None
    apiKey: str | None = None
    transport: Any | None = None
    cacheRetention: Any | None = None
    sessionId: str | None = None
    onPayload: Any | None = None
    onResponse: Any | None = None
    headers: dict[str, str] | None = None
    timeoutMs: int | None = None
    reasoning: ThinkingLevel | None = None
    thinkingBudgets: dict[str, int] | None = None
    # Extra stream options bag
    extra: dict[str, Any] = field(default_factory=dict)

    def to_stream_options(self) -> SimpleStreamOptions:
        opts: SimpleStreamOptions = {}
        if self.temperature is not None:
            opts["temperature"] = self.temperature
        if self.maxTokens is not None:
            opts["maxTokens"] = self.maxTokens
        if self.signal is not None:
            opts["signal"] = self.signal
        if self.apiKey is not None:
            opts["apiKey"] = self.apiKey
        if self.transport is not None:
            opts["transport"] = self.transport
        if self.cacheRetention is not None:
            opts["cacheRetention"] = self.cacheRetention
        if self.sessionId is not None:
            opts["sessionId"] = self.sessionId
        if self.onPayload is not None:
            opts["onPayload"] = self.onPayload
        if self.onResponse is not None:
            opts["onResponse"] = self.onResponse
        if self.headers is not None:
            opts["headers"] = self.headers  # type: ignore[typeddict-item]
        if self.timeoutMs is not None:
            opts["timeoutMs"] = self.timeoutMs
        if self.reasoning is not None:
            opts["reasoning"] = self.reasoning  # type: ignore[typeddict-item]
        if self.thinkingBudgets is not None:
            opts["thinkingBudgets"] = self.thinkingBudgets
        opts.update(self.extra)  # type: ignore[typeddict-item]
        return opts


AgentEventSink: TypeAlias = Callable[[AgentEvent], Awaitable[None] | None]


__all__ = [
    "AfterToolCallContext",
    "AfterToolCallResult",
    "AgentContext",
    "AgentEvent",
    "AgentEventSink",
    "AgentLoopConfig",
    "AgentLoopTurnUpdate",
    "AgentMessage",
    "AgentState",
    "AgentTool",
    "AgentToolCall",
    "AgentToolResult",
    "AgentToolUpdateCallback",
    "BeforeToolCallContext",
    "BeforeToolCallResult",
    "CustomAgentMessage",
    "PrepareNextTurnContext",
    "QueueMode",
    "ShouldStopAfterTurnContext",
    "StreamFn",
    "ThinkingLevel",
    "ToolExecutionMode",
]
