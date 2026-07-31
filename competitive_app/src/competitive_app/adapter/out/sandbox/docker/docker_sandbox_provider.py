"""Async Docker sandbox lifecycle provider.

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/sandbox/docker/docker_sandbox_provider.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see deploy/tool-sandbox/licenses/POIROT-MIT.txt)
Host delta: async FastAPI lifecycle, parent-scope keys, no signal handlers,
no per-call lease/refcount, and hardened Docker backend.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from ..contracts.sandbox_provider import SandboxProvider
from ..guards.audit_guard import AuditGuard
from ..guards.docker_path_guard import DockerPathGuard
from ..sandbox import Sandbox
from ..translators.docker_path_translator import DockerPathTranslator
from ..types import (
    IDLE_SCAN_INTERVAL_SECONDS,
    IDLE_TIMEOUT_SECONDS,
    READINESS_TIMEOUT_SECONDS,
    REPLICAS,
    SandboxInfo,
    require_scope_id,
)
from ..runtimes.docker_runtime import DockerRuntime
from .cross_process_lock import lock_file_exclusive, open_lock_file, unlock_file
from .local_container_backend import LocalContainerBackend
from .readiness import wait_for_sandbox_ready_async

logger = logging.getLogger(__name__)

BackendFactory = Callable[..., Any]
RuntimeFactory = Callable[[str], Any]
ReadinessCheck = Callable[[str], Awaitable[bool]]


class DockerSandboxProvider(SandboxProvider):
    """Own active/warm physical containers for stable logical scopes."""

    uses_thread_data_mounts = True

    def __init__(
        self,
        *,
        image: str,
        sandbox_root: str | Path,
        environment: Mapping[str, str | None] | None = None,
        backend: Any | None = None,
        runtime_factory: RuntimeFactory = DockerRuntime,
        readiness_check: ReadinessCheck | None = None,
        idle_timeout: float = IDLE_TIMEOUT_SECONDS,
        replicas: int = REPLICAS,
        start_idle_checker: bool = True,
    ) -> None:
        self._sandbox_root = Path(sandbox_root)
        self._backend = backend or LocalContainerBackend(
            image=image,
            sandbox_root=self._sandbox_root,
            environment=environment,
        )
        self._runtime_factory = runtime_factory
        self._readiness_check = readiness_check or self._default_readiness
        self._idle_timeout = float(idle_timeout)
        self._replicas = int(replicas)
        if self._replicas < 1:
            raise ValueError("sandbox replicas must be positive")
        self._active: dict[str, Sandbox] = {}
        self._infos: dict[str, SandboxInfo] = {}
        self._warm: dict[str, tuple[SandboxInfo, float]] = {}
        self._last_activity: dict[str, float] = {}
        self._scope_locks: dict[str, asyncio.Lock] = {}
        self._state_lock = asyncio.Lock()
        self._idle_task: asyncio.Task[None] | None = None
        self._started = False
        self._shutdown_called = False
        self._start_idle_checker = start_idle_checker

    async def start(self) -> None:
        """Reconcile orphan containers before the application serves traffic."""
        if self._started:
            return
        if self._shutdown_called:
            raise RuntimeError("sandbox provider is shut down")
        await self._reconcile_orphans()
        self._started = True
        if self._start_idle_checker and self._idle_timeout > 0:
            self._idle_task = asyncio.create_task(self._idle_loop(), name="sandbox-idle-checker")

    async def acquire(self, scope_id: str) -> Sandbox:
        scope_id = require_scope_id(scope_id)
        if self._shutdown_called:
            raise RuntimeError("sandbox provider is shut down")
        lock = self._scope_locks.setdefault(scope_id, asyncio.Lock())
        async with lock:
            if self._shutdown_called:
                raise RuntimeError("sandbox provider is shut down")
            active = self._active.get(scope_id)
            if active is not None:
                info = self._infos.get(scope_id)
                if info is not None and await self._backend.is_alive(info) is not False:
                    self._last_activity[scope_id] = time.monotonic()
                    return active
                await self._drop_scope(scope_id, destroy=True)

            warm = self._warm.pop(scope_id, None)
            if warm is not None:
                info, _ = warm
                if await self._backend.is_alive(info) is not False:
                    sandbox = self._register(scope_id, info)
                    logger.info("Reclaimed warm sandbox %s", scope_id)
                    return sandbox
                await self._destroy_info(scope_id, info)

            lock_file = await asyncio.to_thread(open_lock_file, self._sandbox_root / f"{scope_id}.lock")
            try:
                await asyncio.to_thread(lock_file_exclusive, lock_file)
                # A different process may have created the scope while we were
                # waiting for the cross-process lock.
                discovered = await self._backend.discover(scope_id)
                if discovered is not None:
                    if await self._backend.is_alive(discovered) is False:
                        await self._destroy_info(scope_id, discovered)
                    else:
                        sandbox = self._register(scope_id, discovered)
                        return sandbox
                await self._evict_for_replica()
                info = await self._backend.create(scope_id)
                if not await self._readiness_check(info.sandbox_url):
                    await self._destroy_info(scope_id, info)
                    raise RuntimeError(f"sandbox {scope_id} failed readiness")
                sandbox = self._register(scope_id, info)
                logger.info("Created sandbox %s", scope_id)
                return sandbox
            finally:
                await asyncio.to_thread(unlock_file, lock_file)
                await asyncio.to_thread(lock_file.close)

    async def release(self, scope_id: str) -> None:
        scope_id = require_scope_id(scope_id)
        lock = self._scope_locks.setdefault(scope_id, asyncio.Lock())
        async with lock:
            sandbox = self._active.pop(scope_id, None)
            info = self._infos.pop(scope_id, None)
            self._last_activity.pop(scope_id, None)
            if sandbox is None or info is None:
                return
            await _close_sandbox(sandbox)
            if not self._shutdown_called:
                self._warm[scope_id] = (info, time.monotonic())
                logger.info("Released sandbox %s to warm pool", scope_id)
            else:
                await self._destroy_info(scope_id, info)

    async def destroy_scope(self, scope_id: str) -> None:
        scope_id = require_scope_id(scope_id)
        lock = self._scope_locks.setdefault(scope_id, asyncio.Lock())
        async with lock:
            await self._drop_scope(scope_id, destroy=True)

    async def get_info(self, scope_id: str) -> SandboxInfo | None:
        scope_id = require_scope_id(scope_id)
        return self._infos.get(scope_id) or (self._warm.get(scope_id) or (None,))[0]

    async def shutdown(self) -> None:
        if self._shutdown_called:
            return
        self._shutdown_called = True
        if self._idle_task is not None:
            self._idle_task.cancel()
            await asyncio.gather(self._idle_task, return_exceptions=True)
            self._idle_task = None
        active = [(scope_id, sandbox, self._infos.get(scope_id)) for scope_id, sandbox in self._active.items()]
        warm = list(self._warm.items())
        self._active.clear()
        self._infos.clear()
        self._warm.clear()
        self._last_activity.clear()
        await asyncio.gather(
            *(_close_sandbox(sandbox) for _, sandbox, _ in active),
            return_exceptions=True,
        )
        await asyncio.gather(
            *(self._destroy_info(scope_id, info) for scope_id, _, info in active if info is not None),
            *(self._destroy_info(scope_id, info) for scope_id, (info, _) in warm),
            return_exceptions=True,
        )

    async def _default_readiness(self, url: str) -> bool:
        return await wait_for_sandbox_ready_async(url, timeout=READINESS_TIMEOUT_SECONDS)

    def _register(self, scope_id: str, info: SandboxInfo) -> Sandbox:
        sandbox = Sandbox(
            scope_id,
            self._runtime_factory(info.sandbox_url),
            DockerPathTranslator(self._sandbox_root, scope_id),
            AuditGuard(DockerPathGuard()),
        )
        self._active[scope_id] = sandbox
        self._infos[scope_id] = info
        self._last_activity[scope_id] = time.monotonic()
        return sandbox

    async def _drop_scope(self, scope_id: str, *, destroy: bool) -> None:
        sandbox = self._active.pop(scope_id, None)
        info = self._infos.pop(scope_id, None)
        warm = self._warm.pop(scope_id, None)
        self._last_activity.pop(scope_id, None)
        if sandbox is not None:
            await _close_sandbox(sandbox)
        if destroy:
            if info is not None:
                await self._destroy_info(scope_id, info)
            if warm is not None:
                await self._destroy_info(scope_id, warm[0])

    async def _destroy_info(self, scope_id: str, info: SandboxInfo) -> None:
        try:
            current = await self._backend.discover(scope_id)
        except Exception:  # noqa: BLE001
            current = None
        if current is not None and _container_identity(current) != _container_identity(info):
            logger.warning("Skipping destroy for replaced sandbox %s", scope_id)
            return
        try:
            await self._backend.destroy(info)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to destroy sandbox %s: %s", scope_id, exc)

    async def _evict_for_replica(self) -> None:
        if len(self._active) + len(self._warm) < self._replicas or not self._warm:
            return
        oldest_scope = min(self._warm, key=lambda sid: self._warm[sid][1])
        info, _ = self._warm.pop(oldest_scope)
        await self._destroy_info(oldest_scope, info)

    async def _reconcile_orphans(self) -> None:
        try:
            running = await self._backend.list_running()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sandbox orphan reconciliation failed: %s", exc)
            return
        now = time.monotonic()
        for info in running:
            if not info.sandbox_url or info.sandbox_id in self._active or info.sandbox_id in self._warm:
                continue
            self._warm[info.sandbox_id] = (info, now)

    async def _idle_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(IDLE_SCAN_INTERVAL_SECONDS)
                await self._cleanup_idle()
        except asyncio.CancelledError:
            return

    async def _cleanup_idle(self) -> None:
        now = time.monotonic()
        stale_active = [sid for sid, stamp in self._last_activity.items() if now - stamp > self._idle_timeout]
        stale_warm = [sid for sid, (_, stamp) in self._warm.items() if now - stamp > self._idle_timeout]
        for scope_id in stale_active:
            await self.destroy_scope(scope_id)
        for scope_id in stale_warm:
            info = self._warm.pop(scope_id, (None, 0))[0]
            if info is not None:
                await self._destroy_info(scope_id, info)


def _container_identity(info: SandboxInfo) -> tuple[str | None, str | None]:
    return info.container_id, info.container_name


async def _close_sandbox(sandbox: Sandbox) -> None:
    try:
        await sandbox.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error closing sandbox runtime: %s", exc)


__all__ = ["DockerSandboxProvider"]
