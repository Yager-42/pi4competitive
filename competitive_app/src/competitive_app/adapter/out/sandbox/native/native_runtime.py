"""Native worker runtime — one sandboxed worker per RPC request (NEW-HOST).

P3.3 Phase D (G0 map §6.1): implements the provider-neutral
``SandboxRuntime`` contract over the pi-sandbox runner/broker port. Each
call spawns an independent broker (per-call SRT manager), so an idle scope
holds zero broker/worker/proxy processes (S12).

License: Apache-2.0 (native sandbox license directory)
"""
from __future__ import annotations

import asyncio
import inspect
import os
import stat
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ..exceptions import SandboxCommandError, SandboxRuntimeError
from ..protocol import (
    FrameSequence,
    MAX_DIAGNOSTIC_BYTES,
    RpcFrame,
    RpcProtocolError,
    RpcRequest,
    decode_frame,
    encode_request,
)
from ..types import NO_CHANGE_TIMEOUT_SECONDS
from .policy import create_default_policy
from .runner import SandboxCommandOptions, run_sandboxed_command

WORKER_MODULE = "competitive_app.adapter.out.sandbox.worker"

FrameCallback = Callable[[RpcFrame], Awaitable[None] | None]

#: Legacy path variable; native runs also carry the manifest as an inherited fd.
MANIFEST_ENV = "PI4COMPETITIVE_MANIFEST_PATH"
MANIFEST_FD_ENV = "PI4COMPETITIVE_MANIFEST_FD"


def _validate_directory_descriptor(path: Path, descriptor: int) -> None:
    """Require the path and retained descriptor to name the same directory."""
    try:
        path_stat = os.stat(path, follow_symlinks=False)
        fd_stat = os.fstat(descriptor)
    except OSError as error:
        raise SandboxRuntimeError("sandbox workspace descriptor is unavailable") from error
    if not stat.S_ISDIR(path_stat.st_mode) or not stat.S_ISDIR(fd_stat.st_mode):
        raise SandboxRuntimeError("sandbox workspace is not a directory")
    if (path_stat.st_dev, path_stat.st_ino) != (fd_stat.st_dev, fd_stat.st_ino):
        raise SandboxRuntimeError("sandbox workspace changed during execution")


def _runner_abort_signal(
    scope_signal: asyncio.Future | None,
    call_signal: Any | None,
) -> asyncio.Future | None:
    """Combine the scope abort (provider destroy) and the per-call AgentTool
    abort signal into the runner's single done-future semantics."""
    loop = asyncio.get_running_loop()
    combined = loop.create_future()

    def _fire() -> None:
        if not combined.done():
            combined.set_result(None)

    sources = 0
    if scope_signal is not None:
        sources += 1
        if scope_signal.done():
            _fire()
        else:
            scope_signal.add_done_callback(lambda _fut: _fire())
    if call_signal is not None:
        sources += 1
        if getattr(call_signal, "aborted", False):
            _fire()
        add_listener = getattr(call_signal, "addEventListener", None)
        if add_listener is not None:
            add_listener("abort", _fire)
        else:
            add_done = getattr(call_signal, "add_done_callback", None)
            if add_done is not None:
                add_done(lambda _fut: _fire())
    if sources == 0:
        return None
    return combined


def _additional_allow_read(env: dict[str, str] | None) -> list[str]:
    """PYTHONPATH roots the sandboxed worker must be able to import."""
    pythonpath = (env or {}).get("PYTHONPATH", "")
    roots: list[str] = []
    for entry in pythonpath.split(os.pathsep):
        entry = entry.strip()
        if not entry or not os.path.isabs(entry):
            continue
        if os.path.realpath(entry) == os.path.realpath(sys.prefix):
            continue  # interpreter root is already allow-read
        roots.append(entry)
    return roots


class NativeRuntime:
    """Run the fixed JSONL worker inside one SRT sandbox per request."""

    def __init__(
        self,
        workspace: str | Path,
        *,
        workspace_fd: int | None = None,
        env: dict[str, str] | None = None,
        manifest_path: str | Path | None = None,
        manifest_fd: int | None = None,
        scope_signal: asyncio.Future | None = None,
        broker: dict | None = None,
        no_change_timeout: float = NO_CHANGE_TIMEOUT_SECONDS,
        worker_invocation: dict | None = None,
        additional_allow_read: list[str] | None = None,
    ) -> None:
        self._workspace = Path(workspace)
        if workspace_fd is None:
            try:
                workspace_fd = os.open(
                    self._workspace,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW,
                )
            except OSError as error:
                raise SandboxRuntimeError("sandbox workspace descriptor is unavailable") from error
        else:
            workspace_fd = os.dup(workspace_fd)
        self._workspace_fd = workspace_fd
        try:
            _validate_directory_descriptor(self._workspace, workspace_fd)
        except Exception:
            os.close(workspace_fd)
            raise
        self._env = dict(env or {})
        self._additional_allow_read = list(additional_allow_read or [])
        self._manifest_path = Path(manifest_path) if manifest_path else None
        self._manifest_fd: int | None = None
        try:
            if manifest_fd is not None:
                self._manifest_fd = os.dup(manifest_fd)
                if not stat.S_ISREG(os.fstat(self._manifest_fd).st_mode):
                    raise OSError("manifest descriptor is not a regular file")
        except OSError as error:
            if self._manifest_fd is not None:
                os.close(self._manifest_fd)
            os.close(self._workspace_fd)
            raise SandboxRuntimeError("sandbox manifest descriptor is unavailable") from error
        self._scope_signal = scope_signal
        self._broker = broker
        self._no_change_timeout = float(no_change_timeout)
        self._worker_invocation = worker_invocation or {
            "command": sys.executable,
            "args": ["-m", WORKER_MODULE],
        }
        self._closed = False
        self._active_runs: set[asyncio.Task[Any]] = set()
        self._close_task: asyncio.Task[None] | None = None

    async def execute_worker(
        self,
        request: RpcRequest,
        on_frame: FrameCallback,
        *,
        command: str,
        signal: Any | None = None,
    ) -> RpcFrame:
        if self._closed:
            raise SandboxRuntimeError("sandbox runtime is closed")
        current = asyncio.current_task()
        if current is None:
            raise SandboxRuntimeError("sandbox worker requires an asyncio task")
        self._active_runs.add(current)
        try:
            return await self._execute_worker(
                request, on_frame, command=command, signal=signal
            )
        finally:
            self._active_runs.discard(current)

    async def _execute_worker(
        self,
        request: RpcRequest,
        on_frame: FrameCallback,
        *,
        command: str,
        signal: Any | None = None,
    ) -> RpcFrame:
        if self._closed:
            raise SandboxRuntimeError("sandbox runtime is closed")
        if not command or "\n" in command or "\r" in command:
            raise SandboxRuntimeError("sandbox worker command is invalid")
        _validate_directory_descriptor(self._workspace, self._workspace_fd)
        payload = encode_request(request).decode("utf-8") + "\n"

        worker_env = dict(self._env)
        if self._manifest_fd is not None:
            worker_env[MANIFEST_FD_ENV] = str(self._manifest_fd)
            worker_env[MANIFEST_ENV] = (
                str(self._manifest_path)
                if self._manifest_path is not None
                else f"/dev/fd/{self._manifest_fd}"
            )
        elif self._manifest_path is not None:
            worker_env[MANIFEST_ENV] = str(self._manifest_path)
        policy = create_default_policy(
            str(self._workspace),
            additional_allow_read=list(
                dict.fromkeys(
                    [*_additional_allow_read(self._env), *self._additional_allow_read]
                )
            ),
        )
        _validate_directory_descriptor(self._workspace, self._workspace_fd)
        invocation = self._worker_invocation

        terminal: RpcFrame | None = None
        sequence = FrameSequence()
        pending = ""
        diagnostic = ""

        async def consume_stdout(chunk: bytes) -> None:
            nonlocal terminal, pending
            pending += chunk.decode("utf-8", errors="replace")
            lines = pending.split("\n")
            pending = lines.pop()
            for line in lines:
                if not line.strip():
                    continue
                frame = decode_frame(line)
                if frame.scope_id != request.scope_id or frame.tool_call_id != request.tool_call_id:
                    raise RpcProtocolError(
                        "worker frame identity does not match request", code="identity_mismatch"
                    )
                sequence.accept(frame, encoded_size=len(line))
                callback_result = on_frame(frame)
                if inspect.isawaitable(callback_result):
                    await callback_result
                if frame.is_final:
                    terminal = frame

        def consume_stderr(chunk: bytes) -> None:
            nonlocal diagnostic
            if len(diagnostic) >= MAX_DIAGNOSTIC_BYTES:
                return
            diagnostic += chunk.decode("utf-8", errors="replace")

        def on_start(stdin: asyncio.StreamWriter) -> None:
            stdin.write(payload.encode("utf-8"))
            stdin.write_eof()

        try:
            result = await run_sandboxed_command(
                SandboxCommandOptions(
                    command=command,
                    cwd=str(self._workspace),
                    cwd_fd=self._workspace_fd,
                    env=worker_env,
                    signal=_runner_abort_signal(self._scope_signal, signal),
                    timeout=self._no_change_timeout,
                    direct_invocation=invocation,
                    on_start=on_start,
                    on_stdout=consume_stdout,
                    on_stderr=consume_stderr,
                    broker=self._broker,
                    policy=policy,
                    pass_fds=tuple(
                        fd for fd in (self._workspace_fd, self._manifest_fd)
                        if fd is not None
                    ),
                )
            )
        except TimeoutError as error:
            raise SandboxRuntimeError(
                "sandbox worker produced no output before timeout"
            ) from error
        except RuntimeError as error:
            if str(error) == "aborted":
                raise asyncio.CancelledError("sandbox run aborted") from error
            raise SandboxRuntimeError(
                f"sandbox worker runtime request failed: {error}"
            ) from error

        if terminal is None:
            if result["exit_code"] not in (None, 0):
                raise SandboxCommandError(
                    "sandbox worker exited without a terminal frame",
                    command=command,
                    exit_code=result["exit_code"],
                )
            sequence.finish()  # raises missing_final when nothing was emitted
        return terminal

    async def close(self) -> None:
        if self._close_task is None:
            self._closed = True
            active = tuple(self._active_runs)

            async def finish() -> None:
                if active:
                    await asyncio.gather(*active, return_exceptions=True)
                os.close(self._workspace_fd)
                if self._manifest_fd is not None:
                    os.close(self._manifest_fd)

            self._close_task = asyncio.create_task(finish())
        if asyncio.current_task() in self._active_runs:
            return
        try:
            await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            await self._close_task
            raise

__all__ = [
    "MANIFEST_ENV",
    "MANIFEST_FD_ENV",
    "NativeRuntime",
    "WORKER_MODULE",
    "_additional_allow_read",
    "_runner_abort_signal",
]
