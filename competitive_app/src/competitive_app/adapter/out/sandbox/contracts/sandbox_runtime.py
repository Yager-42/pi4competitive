"""Async worker-frame runtime contract.

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/sandbox/contracts/sandbox_runtime.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see deploy/tool-sandbox/licenses/POIROT-MIT.txt)
Host delta: narrowed to async AgentTool worker frames; file facade and PID
kill APIs are intentionally omitted (ADAPT).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from ..protocol import RpcFrame, RpcRequest


@runtime_checkable
class SandboxRuntime(Protocol):
    async def execute_worker(
        self,
        request: RpcRequest,
        on_frame: Callable[[RpcFrame], Awaitable[None] | None],
        *,
        command: str,
    ) -> RpcFrame: ...

    async def close(self) -> None: ...
