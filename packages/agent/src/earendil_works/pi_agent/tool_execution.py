"""Provider-neutral AgentTool execution seam.

This is a P3.3 host delta: upstream Pi invokes ``AgentTool.execute``
directly and has no executor seam.  The contract deliberately knows nothing
about Docker, the application, or any provider policy.
"""
from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .types import AgentTool, AgentToolResult, AgentToolUpdateCallback


@dataclass(frozen=True, slots=True)
class ToolExecutionTarget:
    """Importable module-level callable identity for remote execution."""

    module: str
    qualname: str


class AgentToolExecutor(Protocol):
    """Transport seam used by the low-level agent loop."""

    async def execute(
        self,
        *,
        scope_id: str,
        tool: AgentTool,
        tool_call_id: str,
        params: Any,
        signal: Any | None,
        on_update: AgentToolUpdateCallback,
    ) -> AgentToolResult: ...


def _unwrap_explicit_lineage(execute: Callable[..., Any]) -> Callable[..., Any]:
    current = execute
    seen: set[int] = set()
    while True:
        identity = id(current)
        if identity in seen:
            raise ValueError("tool callable __wrapped__ lineage contains a cycle")
        seen.add(identity)
        wrapped = getattr(current, "__wrapped__", None)
        if wrapped is None:
            return current
        if not callable(wrapped):
            raise TypeError("tool callable __wrapped__ must be callable")
        current = wrapped


def _has_four_argument_signature(execute: Callable[..., Any]) -> bool:
    try:
        parameters = tuple(inspect.signature(execute).parameters.values())
    except (TypeError, ValueError):
        return False
    if len(parameters) != 4:
        return False
    return all(
        parameter.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        for parameter in parameters
    )


def derive_tool_execution_target(
    execute: Callable[..., Any],
) -> ToolExecutionTarget | None:
    """Derive a safe import target from explicit callable wrapper lineage.

    Unsupported callables intentionally return ``None``.  ``pi_agent`` remains
    compatible with standalone direct tools; the production App registry is
    responsible for turning a missing target into a startup failure.
    """

    try:
        original = _unwrap_explicit_lineage(execute)
    except (TypeError, ValueError):
        return None

    if not inspect.isfunction(original) or not inspect.iscoroutinefunction(original):
        return None
    if not _has_four_argument_signature(original):
        return None

    module = getattr(original, "__module__", None)
    qualname = getattr(original, "__qualname__", None)
    if not isinstance(module, str) or not module:
        return None
    if not isinstance(qualname, str) or not qualname:
        return None
    if "<locals>" in qualname or "<lambda>" in qualname or "." in qualname:
        return None
    try:
        imported = importlib.import_module(module)
        resolved = getattr(imported, qualname)
    except (ImportError, AttributeError, TypeError):
        return None
    if resolved is not original:
        return None
    return ToolExecutionTarget(module=module, qualname=qualname)


class DirectToolExecutor:
    """Upstream-compatible in-process executor for standalone Pi use."""

    async def execute(
        self,
        *,
        scope_id: str,
        tool: AgentTool,
        tool_call_id: str,
        params: Any,
        signal: Any | None,
        on_update: AgentToolUpdateCallback,
    ) -> AgentToolResult:
        del scope_id
        return await tool.execute(tool_call_id, params, signal, on_update)


DIRECT_TOOL_EXECUTOR = DirectToolExecutor()


__all__ = [
    "DIRECT_TOOL_EXECUTOR",
    "AgentToolExecutor",
    "DirectToolExecutor",
    "ToolExecutionTarget",
    "derive_tool_execution_target",
]
