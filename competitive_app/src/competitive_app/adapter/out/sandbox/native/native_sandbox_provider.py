"""Native sandbox lifecycle provider — host workspaces + per-scope abort
(NEW-HOST, Phase D).

P3.3 Phase D (G0 map §6.1): implements the provider-neutral
``SandboxProvider`` contract with host-native scopes. A scope owns exactly
its workspace directory and a per-scope abort signal; brokers are spawned
per call by the runtime, so release leaves zero processes (S12) and
``destroy_scope`` aborts any in-flight worker by killing its broker tree
(S11). There is no warm pool: workspaces persist, processes do not.

License: Apache-2.0 (native sandbox license directory)
"""
from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ..contracts.sandbox_provider import SandboxProvider
from ..exceptions import SandboxPermissionError
from ..sandbox import Sandbox
from ..types import require_scope_id
from .native_runtime import NativeRuntime
from .paths import NativePathTranslator, NativeSecurityGuard
from .workspace import ensure_workspace

#: The only host environment that crosses into the sandboxed worker: the
#: seven provider secrets/endpoints plus the system plumbing the worker
#: needs (interpreter/import/workspace paths). Everything else is denied.
NATIVE_WORKER_ENVIRONMENT = frozenset(
    {
        "TAVILY_API_KEY",
        "TAVILY_API_URL",
        "ANYSEARCH_API_KEY",
        "ANYSEARCH_API_URL",
        "GROK_API_KEY",
        "GROK_API_URL",
        "GROK_MODEL",
        "PATH",
        "PYTHONPATH",
        "HOME",
        "TMPDIR",
        "SHELL",
        "LANG",
        "LC_ALL",
    }
)

RuntimeFactory = Callable[..., NativeRuntime]


def _worker_environment(
    environment: Mapping[str, str | None] | None,
) -> dict[str, str]:
    """Filter to the allowlist, drop unset values, and guarantee a
    PYTHONPATH (the worker imports approved tool bundles the same way the
    App does)."""
    if environment is None:
        source: Mapping[str, str | None] = {
            name: os.environ.get(name) for name in NATIVE_WORKER_ENVIRONMENT
        }
    else:
        source = {
            name: value
            for name, value in environment.items()
            if name in NATIVE_WORKER_ENVIRONMENT
        }
    env = {name: value for name, value in source.items() if value is not None}
    if "PYTHONPATH" not in env:
        env["PYTHONPATH"] = os.pathsep.join(
            entry for entry in sys.path if entry
        )
    return env


class NativeSandboxProvider(SandboxProvider):
    """Own host workspace scopes for the native broker runtime."""

    def __init__(
        self,
        *,
        sandbox_root: str | Path,
        environment: Mapping[str, str | None] | None = None,
        manifest_path: str | Path | None = None,
        runtime_factory: RuntimeFactory = NativeRuntime,
    ) -> None:
        self._sandbox_root = Path(sandbox_root)
        self._environment = _worker_environment(environment)
        self._manifest_path = Path(manifest_path) if manifest_path else None
        self._runtime_factory = runtime_factory
        self._active: dict[str, Sandbox] = {}
        self._signals: dict[str, asyncio.Future] = {}
        self._scope_locks: dict[str, asyncio.Lock] = {}
        self._shutdown_called = False

    async def start(self) -> None:
        """No orphan reconciliation: brokers are per-call children of the
        owning process and cannot outlive it (S10/S12)."""

    async def acquire(self, scope_id: str) -> Sandbox:
        scope_id = require_scope_id(scope_id)
        if self._shutdown_called:
            raise RuntimeError("sandbox provider is shut down")
        lock = self._scope_locks.setdefault(scope_id, asyncio.Lock())
        async with lock:
            if self._shutdown_called:
                raise RuntimeError("sandbox provider is shut down")
            sandbox = self._active.get(scope_id)
            if sandbox is not None:
                return sandbox
            try:
                workspace = ensure_workspace(self._sandbox_root, scope_id)
            except SandboxPermissionError:
                raise
            loop = asyncio.get_running_loop()
            signal = loop.create_future()
            runtime = self._runtime_factory(
                workspace,
                env=self._environment,
                manifest_path=self._manifest_path,
                scope_signal=signal,
            )
            sandbox = Sandbox(
                scope_id,
                runtime,
                NativePathTranslator(),
                NativeSecurityGuard(),
            )
            self._active[scope_id] = sandbox
            self._signals[scope_id] = signal
            return sandbox

    async def release(self, scope_id: str) -> None:
        scope_id = require_scope_id(scope_id)
        lock = self._scope_locks.setdefault(scope_id, asyncio.Lock())
        async with lock:
            sandbox = self._active.pop(scope_id, None)
            signal = self._signals.pop(scope_id, None)
            if sandbox is None:
                return
            await _close_sandbox(sandbox)
            if signal is not None and not signal.done():
                signal.set_result(None)

    async def destroy_scope(self, scope_id: str) -> None:
        """Abort any in-flight worker (kills its broker tree) and close the
        scope. The workspace is preserved; task-delete removes it."""
        scope_id = require_scope_id(scope_id)
        lock = self._scope_locks.setdefault(scope_id, asyncio.Lock())
        async with lock:
            sandbox = self._active.pop(scope_id, None)
            signal = self._signals.pop(scope_id, None)
            if signal is not None and not signal.done():
                signal.set_result(None)
            if sandbox is not None:
                await _close_sandbox(sandbox)

    async def get_info(self, scope_id: str) -> Any:
        """Native scopes have no container identity; active-ness is enough."""
        del scope_id
        return None

    async def shutdown(self) -> None:
        if self._shutdown_called:
            return
        self._shutdown_called = True
        signals = list(self._signals.values())
        sandboxes = list(self._active.values())
        self._signals.clear()
        self._active.clear()
        for signal in signals:
            if not signal.done():
                signal.set_result(None)
        await asyncio.gather(
            *(_close_sandbox(sandbox) for sandbox in sandboxes),
            return_exceptions=True,
        )


async def _close_sandbox(sandbox: Sandbox) -> None:
    try:
        await sandbox.close()
    except Exception:  # noqa: BLE001 — best-effort close
        return


__all__ = [
    "NATIVE_WORKER_ENVIRONMENT",
    "NativeSandboxProvider",
    "_worker_environment",
]
