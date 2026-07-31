"""Async scope-oriented sandbox provider contract.

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/sandbox/contracts/sandbox_provider.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see deploy/tool-sandbox/licenses/POIROT-MIT.txt)
Host delta: async acquire/release/destroy_scope/shutdown and parent scope
identity; no per-call lease/refcount (ADAPT).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from ..sandbox import Sandbox
    from ..types import SandboxInfo


@runtime_checkable
class SandboxProvider(Protocol):
    async def acquire(self, scope_id: str) -> "Sandbox": ...

    async def release(self, scope_id: str) -> None: ...

    async def destroy_scope(self, scope_id: str) -> None: ...

    async def get_info(self, scope_id: str) -> "SandboxInfo | None": ...

    async def shutdown(self) -> None: ...
