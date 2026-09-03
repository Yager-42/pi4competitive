"""Sandbox AgentToolExecutor — run approved capability tools in the native worker.

NEW-HOST: no Poirot counterpart.  This adapter binds Pi's provider-neutral
``AgentToolExecutor`` seam (``pi_agent.tool_execution``) to the production
sandbox provider: the model never supplies a target, the registry is the
sole source of tool bindings, and every execution happens inside the
hardened sandbox.

Lifecycle contract (plan E3): ``execute`` acquires lazily and never releases.
The outer session/task run owns the single release; a run that made no tool
call creates no scope.

P3.3 Phase D (G0 map §6.1): the per-call ``signal`` is propagated to the
sandbox so a native invocation aborts by killing its broker tree; the
Docker product path destroyed the scope instead.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from earendil_works.pi_agent.types import AgentTool, AgentToolResult

from .contracts.sandbox_provider import SandboxProvider
from .exceptions import SandboxError
from .approved_registry import ApprovedToolRegistry
from .protocol import PROTOCOL_VERSION, RpcFrame, RpcRequest

FrameCallback = Callable[[RpcFrame], Awaitable[None] | None]

#: Attempts per tool call, including the first. Only errors the worker marked
#: retryable are re-attempted, so a wrong request still fails once.
TOOL_MAX_ATTEMPTS = 3

#: First backoff pause; doubles per retry (1s, 2s). Short on purpose: a search
#: sits on the critical path of a cell the coverage loop is waiting for.
TOOL_RETRY_BASE_DELAY_SECONDS = 1.0


class SandboxToolExecutionError(SandboxError):
    """A worker request ended in an error frame (stable safe message only)."""

    def __init__(self, message: str, *, code: str | None = None, retryable: bool = False) -> None:
        super().__init__(message, details={"code": code or "sandbox_error", "retryable": retryable})


class SandboxToolExecutor:
    """Execute approved tools inside one hardened sandbox per scope."""

    def __init__(
        self,
        *,
        registry: ApprovedToolRegistry,
        provider: SandboxProvider,
    ) -> None:
        self._registry = registry
        self._provider = provider

    @property
    def provider(self) -> SandboxProvider:
        return self._provider

    async def execute(
        self,
        *,
        scope_id: str,
        tool: AgentTool,
        tool_call_id: str,
        params: Any,
        signal: Any | None,
        on_update: Callable[[AgentToolResult], None],
    ) -> AgentToolResult:
        """Run one approved tool, re-attempting worker-declared transient faults.

        A lost connection or a 429 is a property of the attempt, not of the
        request: each call gets a fresh broker and worker process, so a retry
        starts clean. Retrying is skipped once the tool has streamed an update,
        because the caller has already seen partial content that a second
        attempt would contradict.
        """
        binding = self._registry.binding_for(tool)
        request = RpcRequest(
            protocol_version=PROTOCOL_VERSION,
            scope_id=scope_id,
            tool_call_id=tool_call_id,
            tool_name=tool.name,
            target=binding.to_mapping(),
            arguments=params,
        )
        sandbox = await self._provider.acquire(scope_id)

        for attempt in range(1, TOOL_MAX_ATTEMPTS + 1):
            delivered_terminal: RpcFrame | None = None
            streamed = False

            async def deliver(frame: RpcFrame) -> None:
                nonlocal delivered_terminal, streamed
                if frame.is_final:
                    delivered_terminal = frame
                if frame.type == "update" and frame.result is not None:
                    streamed = True
                    on_update(
                        AgentToolResult(
                            content=frame.result.get("content"),
                            details=frame.result.get("details"),
                        )
                    )

            returned_terminal = await sandbox.execute_worker(request, deliver, signal=signal)
            terminal = delivered_terminal or returned_terminal
            if terminal.type != "error":
                result = terminal.result or {}
                return AgentToolResult(
                    content=result.get("content"),
                    details=result.get("details"),
                    usage=result.get("usage"),
                    addedToolNames=result.get("addedToolNames"),
                    terminate=result.get("terminate"),
                )

            error = terminal.error or {}
            retryable = bool(error.get("retryable"))
            if not retryable or streamed or attempt >= TOOL_MAX_ATTEMPTS:
                raise SandboxToolExecutionError(
                    str(error.get("safeMessage") or "sandbox tool failed"),
                    code=str(error.get("code") or "") or None,
                    retryable=retryable,
                )
            await asyncio.sleep(TOOL_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))

        raise AssertionError("unreachable: the loop returns or raises on every attempt")


__all__ = [
    "TOOL_MAX_ATTEMPTS",
    "TOOL_RETRY_BASE_DELAY_SECONDS",
    "SandboxToolExecutionError",
    "SandboxToolExecutor",
]
