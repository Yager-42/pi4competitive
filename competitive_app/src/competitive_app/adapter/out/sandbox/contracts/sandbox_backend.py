"""Async sandbox backend contract.

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/sandbox/contracts/sandbox_backend.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see deploy/tool-sandbox/licenses/POIROT-MIT.txt)
Host delta: async CRUD with fixed hardening/resource identity and no
arbitrary mounts (ADAPT).
"""
from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol, runtime_checkable

from ..types import SandboxInfo


@runtime_checkable
class SandboxBackend(Protocol):
    async def create(self, scope_id: str) -> SandboxInfo: ...

    async def destroy(self, info: SandboxInfo) -> None: ...

    async def is_alive(self, info: SandboxInfo) -> bool | None: ...

    async def discover(self, scope_id: str) -> SandboxInfo | None: ...

    async def list_running(self) -> list[SandboxInfo]: ...
