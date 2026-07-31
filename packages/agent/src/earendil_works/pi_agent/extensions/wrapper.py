"""Extension tool wrappers.

upstream: packages/coding-agent/src/core/extensions/wrapper.ts
"""
from __future__ import annotations

import inspect
import sys
from functools import wraps
from typing import Any
from pathlib import Path

from earendil_works.pi_agent.types import AgentTool
from earendil_works.pi_agent.tool_execution import (
    ToolExecutionTarget,
    derive_tool_execution_target,
)

from .runner import ExtensionRunner
from .types import RegisteredTool, SourceInfo


def _remap_generated_module(
    target: ToolExecutionTarget,
    source_info: SourceInfo,
    root: str | Path,
) -> ToolExecutionTarget:
    """Remap a loader-generated ``pi_extension_*`` module to its real path.

    P3.3 host delta: the local loader imports extension entry files under
    generated module names (``pi_extension_<hash>``), but the derived sandbox
    image ships the same files under their real ``<root>.<relpath>`` module
    path.  Functions already imported from real modules keep their names.
    """
    if not target.module.startswith("pi_extension_"):
        return target
    path = source_info.path
    if not path or path.startswith("<") or not path.endswith(".py"):
        return target
    root_path = Path(root).resolve()
    raw = Path(path)
    try:
        rel = raw.resolve().relative_to(root_path) if raw.is_absolute() else raw
    except ValueError:
        return target
    parts = rel.with_suffix("").parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        return target

    real_name = f"{root_path.name}.{'.'.join(parts)}"
    # Host delta (P3.3): also publish the generated module object under its
    # real name so host-side lineage checks can import the same file object
    # even when the package root is not importable from sys.path (pytest,
    # packaged installs).  The worker image imports the real path fresh.
    if real_name not in sys.modules:
        generated = sys.modules.get(target.module)
        if generated is not None:
            sys.modules[real_name] = generated
    return ToolExecutionTarget(
        module=real_name,
        qualname=target.qualname,
    )



def wrap_registered_tool(registered_tool: RegisteredTool, runner: ExtensionRunner) -> AgentTool:
    definition = registered_tool.definition
    execute = definition.execute
    execution_target = definition.executionTarget
    if execution_target is None:
        derived = derive_tool_execution_target(execute)
        if derived is not None:
            execution_target = _remap_generated_module(derived, registered_tool.sourceInfo, runner.cwd)
    accepts_context = len(inspect.signature(execute).parameters) >= 5
    @wraps(execute)
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
        executionTarget=execution_target,
    )


def wrap_registered_tools(
    registered_tools: list[RegisteredTool], runner: ExtensionRunner
) -> list[AgentTool]:
    return [wrap_registered_tool(tool, runner) for tool in registered_tools]


__all__ = ["wrap_registered_tool", "wrap_registered_tools"]
