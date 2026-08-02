"""Sandbox facade for one fixed AgentTool worker command.

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/sandbox/sandbox.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see deploy/tool-sandbox/licenses/POIROT-MIT.txt)
Host delta (P3.3 Phase D, G0 map §6.1): validate -> translate -> execute ->
mask is narrowed to the fixed JSON worker command; file facade methods are
omitted; ``execute_worker`` additionally forwards the optional per-call
abort ``signal`` to the runtime so a native invocation can be killed
(Docker product abort destroys the scope instead and ignores it).
"""
from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from .contracts import PathTranslator, SandboxRuntime, SecurityGuard
from .protocol import RpcFrame, RpcRequest

FIXED_WORKER_COMMAND = "python -m competitive_app.adapter.out.sandbox.worker"


def _mask_value(value: Any, mask_output: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return mask_output(value)
    if isinstance(value, list):
        return [_mask_value(item, mask_output) for item in value]
    if isinstance(value, dict):
        return {key: _mask_value(child, mask_output) for key, child in value.items()}
    return value


class Sandbox:
    """Compose runtime, fixed path translator, and security guard."""

    def __init__(
        self,
        sandbox_id: str,
        runtime: SandboxRuntime,
        translator: PathTranslator,
        guard: SecurityGuard,
    ) -> None:
        self._id = sandbox_id
        self._runtime = runtime
        self._translator = translator
        self._guard = guard

    @property
    def id(self) -> str:
        return self._id

    def get_host_path(self, virtual_path: str) -> str:
        reverse_translate = getattr(self._translator, "reverse_translate", None)
        if reverse_translate is None:
            raise ValueError("sandbox translator does not expose host path reversal")
        return reverse_translate(virtual_path)

    async def execute_worker(
        self,
        request: RpcRequest,
        on_frame: Callable[[RpcFrame], Awaitable[None] | None],
        *,
        signal: Any | None = None,
    ) -> RpcFrame:
        self._guard.validate_command(FIXED_WORKER_COMMAND)
        command = self._translator.translate_command(FIXED_WORKER_COMMAND)

        async def deliver(frame: RpcFrame) -> None:
            masked = _mask_value(frame.to_mapping(), self._translator.mask_output)
            masked_frame = RpcFrame(
                protocol_version=masked["protocolVersion"],
                scope_id=masked["scopeId"],
                tool_call_id=masked["toolCallId"],
                sequence=masked["sequence"],
                type=masked["type"],
                result=masked.get("result"),
                error=masked.get("error"),
            )
            result = on_frame(masked_frame)
            if inspect.isawaitable(result):
                await result

        terminal = await self._runtime.execute_worker(
            request, deliver, command=command, signal=signal
        )
        return terminal

    async def close(self) -> None:
        await self._runtime.close()


__all__ = ["FIXED_WORKER_COMMAND", "Sandbox"]
