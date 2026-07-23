"""earendil_works.pi_agent — Python isomorphic port of @earendil-works/pi-agent-core.

upstream: packages/agent/src/index.ts
"""
from __future__ import annotations

from earendil_works.pi_ai import uuidv7

from .stream_fn import get_default_stream_fn, set_default_stream_fn
from .types import (
    AfterToolCallContext,
    AfterToolCallResult,
    AgentContext,
    AgentEvent,
    AgentEventSink,
    AgentLoopConfig,
    AgentLoopTurnUpdate,
    AgentMessage,
    AgentTool,
    AgentToolCall,
    AgentToolResult,
    AgentToolUpdateCallback,
    BeforeToolCallContext,
    BeforeToolCallResult,
    PrepareNextTurnContext,
    QueueMode,
    ShouldStopAfterTurnContext,
    StreamFn,
    ThinkingLevel,
    ToolExecutionMode,
)

__all__ = [
    "AfterToolCallContext",
    "AfterToolCallResult",
    "AgentContext",
    "AgentEvent",
    "AgentEventSink",
    "AgentLoopConfig",
    "AgentLoopTurnUpdate",
    "AgentMessage",
    "AgentTool",
    "AgentToolCall",
    "AgentToolResult",
    "AgentToolUpdateCallback",
    "BeforeToolCallContext",
    "BeforeToolCallResult",
    "PrepareNextTurnContext",
    "QueueMode",
    "ShouldStopAfterTurnContext",
    "StreamFn",
    "ThinkingLevel",
    "ToolExecutionMode",
    "get_default_stream_fn",
    "set_default_stream_fn",
    "uuidv7",
]

__version__ = "0.81.1"
