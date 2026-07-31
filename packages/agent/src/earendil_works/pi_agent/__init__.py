"""earendil_works.pi_agent — Python isomorphic port of @earendil-works/pi-agent-core.

upstream: packages/agent/src/index.ts
"""
from __future__ import annotations

from earendil_works.pi_ai import uuidv7

from .agent import AbortController, AbortSignal, Agent, AgentOptions
from .agent_loop import agent_loop, agent_loop_continue, run_agent_loop, run_agent_loop_continue
from .extensions import (
    ExtensionAPI,
    ExtensionRunner,
    attach_extension_runtime,
    create_extension_runtime,
    load_extension_from_factory,
    load_extensions,
    wrap_registered_tool,
    wrap_registered_tools,
)
from .harness import (
    AgentHarness,
    DEFAULT_SESSIONS_DIR_NAME,
    InMemorySessionRepo,
    JsonlSessionRepo,
    Session,
    Skill,
    build_system_prompt,
    compact,
    create_coding_tools,
    create_read_tool,
    create_write_tool,
    should_compact,
)
from .harness.compaction import (
    estimate_context_tokens,
    find_cut_point,
    prepare_compaction,
)
from .harness.session import (
    InMemorySessionStorage,
    JsonlSessionStorage,
    build_session_context,
)
from .package_manager import (
    LocalPackageManager,
    LoadReport,
    apply_capability_report,
    load_capability_packages,
    load_capability_packages_sync,
)
from .stream_fn import get_default_stream_fn, set_default_stream_fn
from .tool_execution import (
    DIRECT_TOOL_EXECUTOR,
    AgentToolExecutor,
    DirectToolExecutor,
    ToolExecutionTarget,
    derive_tool_execution_target,
)
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
    "AbortController",
    "AbortSignal",
    "AfterToolCallContext",
    "AfterToolCallResult",
    "Agent",
    "AgentContext",
    "AgentEvent",
    "AgentEventSink",
    "AgentHarness",
    "AgentLoopConfig",
    "AgentLoopTurnUpdate",
    "AgentMessage",
    "AgentOptions",
    "AgentTool",
    "DIRECT_TOOL_EXECUTOR",
    "AgentToolExecutor",
    "DirectToolExecutor",
    "ToolExecutionTarget",
    "derive_tool_execution_target",
    "AgentToolCall",
    "AgentToolResult",
    "AgentToolUpdateCallback",
    "BeforeToolCallContext",
    "BeforeToolCallResult",
    "DEFAULT_SESSIONS_DIR_NAME",
    "ExtensionAPI",
    "ExtensionRunner",
    "InMemorySessionRepo",
    "InMemorySessionStorage",
    "JsonlSessionRepo",
    "JsonlSessionStorage",
    "LoadReport",
    "LocalPackageManager",
    "PrepareNextTurnContext",
    "QueueMode",
    "Session",
    "ShouldStopAfterTurnContext",
    "Skill",
    "StreamFn",
    "ThinkingLevel",
    "ToolExecutionMode",
    "agent_loop",
    "agent_loop_continue",
    "attach_extension_runtime",
    "build_session_context",
    "build_system_prompt",
    "compact",
    "create_coding_tools",
    "create_extension_runtime",
    "create_read_tool",
    "apply_capability_report",
    "load_capability_packages",
    "load_capability_packages_sync",
    "load_extension_from_factory",
    "load_extensions",
    "create_write_tool",
    "estimate_context_tokens",
    "find_cut_point",
    "get_default_stream_fn",
    "prepare_compaction",
    "run_agent_loop",
    "run_agent_loop_continue",
    "set_default_stream_fn",
    "should_compact",
    "uuidv7",
    "wrap_registered_tool",
    "wrap_registered_tools",
]

__version__ = "0.81.1"
