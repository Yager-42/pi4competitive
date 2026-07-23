"""earendil_works.pi_agent — Python isomorphic port of @earendil-works/pi-agent-core.

upstream: packages/agent/src/index.ts
"""
from __future__ import annotations

from earendil_works.pi_ai import uuidv7

from .agent_loop import agent_loop, agent_loop_continue, run_agent_loop, run_agent_loop_continue
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
    "agent_loop",
    "agent_loop_continue",
    "get_default_stream_fn",
    "run_agent_loop",
    "run_agent_loop_continue",
    "set_default_stream_fn",
    "uuidv7",
]

__version__ = "0.81.1"
