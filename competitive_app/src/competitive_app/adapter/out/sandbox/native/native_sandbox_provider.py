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
import shutil
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

def _stage_manifest(source: Path, workspace: Path) -> Path:
    """Copy the trusted manifest without following a worker-created symlink."""
    destination = workspace / "approved_tools.json"
    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        directory_fd = os.open(
            workspace,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW,
        )
        file_fd = os.open(
            destination.name,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        with source.open("rb") as source_file, os.fdopen(file_fd, "wb") as target_file:
            file_fd = None
            shutil.copyfileobj(source_file, target_file)
    except OSError as error:
        raise SandboxPermissionError(
            "native manifest destination is unsafe",
            path=str(destination),
            operation="workspace",
        ) from error
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)
    return destination


class NativeSandboxProvider(SandboxProvider):
    """Own host workspace scopes for the native broker runtime."""

    def __init__(
        self,
        *,
        sandbox_root: str | Path,
        environment: Mapping[str, str | None] | None = None,
        manifest_path: str | Path | None = None,
        runtime_factory: RuntimeFactory = NativeRuntime,
        additional_allow_read: list[str] | None = None,
    ) -> None:
        self._sandbox_root = Path(sandbox_root)
        self._environment = _worker_environment(environment)
        self._manifest_path = Path(manifest_path) if manifest_path else None
        self._runtime_factory = runtime_factory
        self._additional_allow_read = list(additional_allow_read or [])
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
            # The worker may only read inside its workspace, so the trusted
            # manifest is staged there on acquire (the SRT policy does not
            # allow the sandbox root).
            staged_manifest = None
            if self._manifest_path is not None:
                try:
                    staged_manifest = _stage_manifest(self._manifest_path, workspace)
                except SandboxPermissionError:
                    raise
                except OSError as error:
                    raise SandboxPermissionError(
                        "native manifest is unavailable",
                        path=str(self._manifest_path),
                        operation="workspace",
                    ) from error
            loop = asyncio.get_running_loop()
            signal = loop.create_future()
            runtime = self._runtime_factory(
                workspace,
                env=self._environment,
                manifest_path=staged_manifest,
                scope_signal=signal,
                additional_allow_read=self._additional_allow_read,
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
            # Close is only an admission flag on NativeRuntime; signal first
            # so an already-running command is killed before scope teardown.
            if signal is not None and not signal.done():
                signal.set_result(None)
            await _close_sandbox(sandbox)
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
