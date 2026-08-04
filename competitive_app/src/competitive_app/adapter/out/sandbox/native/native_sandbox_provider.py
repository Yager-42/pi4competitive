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
from .workspace import open_workspace_descriptor

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

def _stage_manifest_descriptor(
    source: Path,
    workspace: Path,
    *,
    directory_fd: int | None = None,
) -> tuple[Path, int]:
    """Stage and retain the manifest descriptor opened relative to workspace."""
    destination = workspace / "approved_tools.json"
    owned_directory_fd = directory_fd is None
    opened_fd: int | None = None
    file_fd: int | None = None
    try:
        if directory_fd is None:
            opened_fd = os.open(
                workspace,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW,
            )
            directory_fd = opened_fd
        for _attempt in range(3):
            try:
                try:
                    os.unlink(destination.name, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass
                file_fd = os.open(
                    destination.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory_fd,
                )
                break
            except FileExistsError:
                continue
        else:
            raise FileExistsError(destination.name)
        with source.open("rb") as source_file, os.fdopen(
            file_fd, "wb", closefd=False
        ) as target_file:
            shutil.copyfileobj(source_file, target_file)
            target_file.flush()
            os.fsync(file_fd)
        assert file_fd is not None
        write_stat = os.fstat(file_fd)
        read_fd: int | None = None
        try:
            read_fd = os.open(
                destination.name,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
            read_stat = os.fstat(read_fd)
            if (write_stat.st_dev, write_stat.st_ino) != (read_stat.st_dev, read_stat.st_ino):
                raise OSError("manifest destination changed during staging")
            os.close(file_fd)
            file_fd = None
            return destination, read_fd
        except Exception:
            if read_fd is not None:
                os.close(read_fd)
            raise
    except OSError as error:
        raise SandboxPermissionError(
            "native manifest destination is unsafe",
            path=str(destination),
            operation="workspace",
        ) from error
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if owned_directory_fd and opened_fd is not None:
            os.close(opened_fd)


def _stage_manifest(
    source: Path,
    workspace: Path,
    *,
    directory_fd: int | None = None,
) -> Path:
    """Copy a trusted manifest without following worker-created links."""
    destination, manifest_fd = _stage_manifest_descriptor(
        source, workspace, directory_fd=directory_fd
    )
    os.close(manifest_fd)
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
        self._workspace_fds: dict[str, int] = {}
        self._manifest_fds: dict[str, int] = {}
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
            workspace_fd: int | None = None
            manifest_fd: int | None = None
            try:
                workspace, workspace_fd = open_workspace_descriptor(
                    self._sandbox_root, scope_id
                )
                staged_manifest = None
                if self._manifest_path is not None:
                    staged_manifest, manifest_fd = _stage_manifest_descriptor(
                        self._manifest_path,
                        workspace,
                        directory_fd=workspace_fd,
                    )
                loop = asyncio.get_running_loop()
                signal = loop.create_future()
                runtime: Any = None
                try:
                    runtime = self._runtime_factory(
                        workspace,
                        workspace_fd=workspace_fd,
                        env=self._environment,
                        manifest_path=staged_manifest,
                        manifest_fd=manifest_fd,
                        scope_signal=signal,
                        additional_allow_read=self._additional_allow_read,
                    )
                    sandbox = Sandbox(
                        scope_id,
                        runtime,
                        NativePathTranslator(),
                        NativeSecurityGuard(),
                    )
                except Exception:
                    if runtime is not None:
                        await runtime.close()
                    raise
            except Exception:
                if manifest_fd is not None:
                    os.close(manifest_fd)
                if workspace_fd is not None:
                    os.close(workspace_fd)
                raise
            self._active[scope_id] = sandbox
            self._signals[scope_id] = signal
            if manifest_fd is not None:
                self._manifest_fds[scope_id] = manifest_fd
            self._workspace_fds[scope_id] = workspace_fd
            return sandbox

    async def release(self, scope_id: str) -> None:
        scope_id = require_scope_id(scope_id)
        lock = self._scope_locks.setdefault(scope_id, asyncio.Lock())
        async with lock:
            sandbox = self._active.pop(scope_id, None)
            signal = self._signals.pop(scope_id, None)
            workspace_fd = self._workspace_fds.pop(scope_id, None)
            manifest_fd = self._manifest_fds.pop(scope_id, None)
            if sandbox is None:
                if manifest_fd is not None:
                    os.close(manifest_fd)
                if workspace_fd is not None:
                    os.close(workspace_fd)
                return
            # Close is only an admission flag on NativeRuntime; signal first
            # so an already-running command is killed before scope teardown.
            if signal is not None and not signal.done():
                signal.set_result(None)
            await _close_sandbox(sandbox)
            if workspace_fd is not None:
                os.close(workspace_fd)
            if manifest_fd is not None:
                os.close(manifest_fd)

    async def destroy_scope(self, scope_id: str) -> None:
        """Abort any in-flight worker (kills its broker tree) and close the
        scope. The workspace is preserved; task-delete removes it."""
        scope_id = require_scope_id(scope_id)
        lock = self._scope_locks.setdefault(scope_id, asyncio.Lock())
        async with lock:
            sandbox = self._active.pop(scope_id, None)
            signal = self._signals.pop(scope_id, None)
            workspace_fd = self._workspace_fds.pop(scope_id, None)
            manifest_fd = self._manifest_fds.pop(scope_id, None)
            if signal is not None and not signal.done():
                signal.set_result(None)
            if sandbox is not None:
                await _close_sandbox(sandbox)
            if manifest_fd is not None:
                os.close(manifest_fd)
            if workspace_fd is not None:
                os.close(workspace_fd)

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
        workspace_fds = list(self._workspace_fds.values())
        manifest_fds = list(self._manifest_fds.values())
        self._signals.clear()
        self._active.clear()
        self._workspace_fds.clear()
        self._manifest_fds.clear()
        for signal in signals:
            if not signal.done():
                signal.set_result(None)
        await asyncio.gather(
            *(_close_sandbox(sandbox) for sandbox in sandboxes),
            return_exceptions=True,
        )
        for workspace_fd in workspace_fds:
            os.close(workspace_fd)
        for manifest_fd in manifest_fds:
            os.close(manifest_fd)


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
