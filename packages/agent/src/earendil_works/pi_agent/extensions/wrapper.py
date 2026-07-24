"""Extension tool wrappers.

upstream: packages/coding-agent/src/core/extensions/wrapper.ts
"""
from __future__ import annotations

import inspect
from typing import Any

from earendil_works.pi_agent.types import AgentTool

from .runner import ExtensionRunner
from .types import RegisteredTool


def wrap_registered_tool(registered_tool: RegisteredTool, runner: ExtensionRunner) -> AgentTool:
    definition = registered_tool.definition
    execute = definition.execute
    accepts_context = len(inspect.signature(execute).parameters) >= 5

    async def wrapped(tool_call_id: str, params: Any, signal: Any = None, on_update: Any = None):
        if accepts_context:
            return await execute(tool_call_id, params, signal, on_update, runner.create_context())
        return await execute(tool_call_id, params, signal, on_update)

    return AgentTool(
        name=definition.name,
        description=definition.description,
        parameters=definition.parameters,
        label=definition.label,
        execute=wrapped,
        prepareArguments=definition.prepareArguments,
        executionMode=definition.executionMode,
    )


def wrap_registered_tools(
    registered_tools: list[RegisteredTool], runner: ExtensionRunner
) -> list[AgentTool]:
    return [wrap_registered_tool(tool, runner) for tool in registered_tools]


__all__ = ["wrap_registered_tool", "wrap_registered_tools"]
