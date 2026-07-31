"""Sandbox AgentToolExecutor — run approved capability tools in the Docker worker.

NEW-HOST: no Poirot counterpart.  This adapter binds Pi's provider-neutral
``AgentToolExecutor`` seam (``pi_agent.tool_execution``) to the production
``DockerSandboxProvider``: the model never supplies a target, the registry is
the sole source of tool bindings, and every execution happens inside the
hardened worker image.

Lifecycle contract (plan E3): ``execute`` acquires lazily and never releases.
The outer session/task run owns the single release; a run that made no tool
call creates no container.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from earendil_works.pi_agent.types import AgentTool, AgentToolResult

from .contracts.sandbox_provider import SandboxProvider
from .exceptions import SandboxError
from .approved_registry import ApprovedToolRegistry
from .protocol import PROTOCOL_VERSION, RpcFrame, RpcRequest

FrameCallback = Callable[[RpcFrame], Awaitable[None] | None]


class SandboxToolExecutionError(SandboxError):
    """A worker request ended in an error frame (stable safe message only)."""

    def __init__(self, message: str, *, code: str | None = None, retryable: bool = False) -> None:
        super().__init__(message, details={"code": code or "sandbox_error", "retryable": retryable})


class SandboxToolExecutor:
    """Execute approved tools inside one hardened sandbox container per scope."""

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
        del signal  # worker-local abort signal; product abort destroys the scope
        binding = self._registry.binding_for(tool)
        request = RpcRequest(
            protocol_version=PROTOCOL_VERSION,
            scope_id=scope_id,
            tool_call_id=tool_call_id,
            tool_name=tool.name,
            target=binding.to_mapping(),
            arguments=params,
        )

        async def deliver(frame: RpcFrame) -> None:
            if frame.type == "update" and frame.result is not None:
                on_update(
                    AgentToolResult(
                        content=frame.result.get("content"),
                        details=frame.result.get("details"),
                    )
                )

        sandbox = await self._provider.acquire(scope_id)
        terminal = await sandbox.execute_worker(request, deliver)
        if terminal.type == "error":
            error = terminal.error or {}
            raise SandboxToolExecutionError(
                str(error.get("safeMessage") or "sandbox tool failed"),
                code=str(error.get("code") or "") or None,
                retryable=bool(error.get("retryable")),
            )
        result = terminal.result or {}
        return AgentToolResult(
            content=result.get("content"),
            details=result.get("details"),
            usage=result.get("usage"),
            addedToolNames=result.get("addedToolNames"),
            terminate=result.get("terminate"),
        )


__all__ = ["SandboxToolExecutionError", "SandboxToolExecutor"]
