"""Agent-engine extension runtime.

upstream: packages/coding-agent/src/core/extensions/index.ts
"""
from .loader import create_extension_runtime, load_extension_from_factory, load_extensions
from .runner import ExtensionRunner
from .types import (
    Extension,
    ExtensionAPI,
    ExtensionContext,
    ExtensionError,
    ExtensionRuntime,
    IN_EVENTS,
    LoadExtensionsResult,
    OUT_EVENTS,
    RegisteredTool,
    SourceInfo,
)
from .wrapper import wrap_registered_tool, wrap_registered_tools


def attach_extension_runtime(agent, result: LoadExtensionsResult, cwd: str, *, replace: bool = False):
    """Attach one loaded runtime and its wrapped tools to an Agent."""
    runner = ExtensionRunner.from_load_result(result, cwd)
    agent.set_extension_runner(runner)
    incoming = wrap_registered_tools(runner.get_all_registered_tools(), runner)
    if replace:
        by_name = {tool.name: tool for tool in agent.state.tools}
        by_name.update({tool.name: tool for tool in incoming})
        agent.state.tools = list(by_name.values())
    else:
        seen = {tool.name for tool in agent.state.tools}
        agent.state.tools = [*agent.state.tools, *(tool for tool in incoming if tool.name not in seen)]
    return runner

__all__ = [
    "Extension", "ExtensionAPI", "ExtensionContext", "ExtensionError", "ExtensionRunner",
    "ExtensionRuntime", "IN_EVENTS", "LoadExtensionsResult", "OUT_EVENTS", "RegisteredTool",
    "SourceInfo", "attach_extension_runtime", "create_extension_runtime",
    "load_extension_from_factory", "load_extensions", "wrap_registered_tool",
    "wrap_registered_tools",
]
