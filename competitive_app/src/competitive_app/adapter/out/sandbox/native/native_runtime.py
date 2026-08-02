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

#: Env var carrying the trusted approved-tool manifest path into the worker.
MANIFEST_ENV = "PI4COMPETITIVE_MANIFEST_PATH"


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
        env: dict[str, str] | None = None,
        manifest_path: str | Path | None = None,
        scope_signal: asyncio.Future | None = None,
        broker: dict | None = None,
        no_change_timeout: float = NO_CHANGE_TIMEOUT_SECONDS,
        worker_invocation: dict | None = None,
        additional_allow_read: list[str] | None = None,
    ) -> None:
        self._workspace = Path(workspace)
        self._env = dict(env or {})
        self._additional_allow_read = list(additional_allow_read or [])
        self._manifest_path = Path(manifest_path) if manifest_path else None
        self._scope_signal = scope_signal
        self._broker = broker
        self._no_change_timeout = float(no_change_timeout)
        self._worker_invocation = worker_invocation or {
            "command": sys.executable,
            "args": ["-m", WORKER_MODULE],
        }
        self._closed = False

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
        if not command or "\n" in command or "\r" in command:
            raise SandboxRuntimeError("sandbox worker command is invalid")
        payload = encode_request(request).decode("utf-8") + "\n"

        worker_env = dict(self._env)
        if self._manifest_path is not None:
            worker_env[MANIFEST_ENV] = str(self._manifest_path)
        policy = create_default_policy(
            str(self._workspace),
            additional_allow_read=list(
                dict.fromkeys(
                    [*_additional_allow_read(self._env), *self._additional_allow_read]
                )
            ),
        )
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
                    env=worker_env,
                    signal=_runner_abort_signal(self._scope_signal, signal),
                    timeout=self._no_change_timeout,
                    direct_invocation=invocation,
                    on_start=on_start,
                    on_stdout=consume_stdout,
                    on_stderr=consume_stderr,
                    broker=self._broker,
                    policy=policy,
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
        self._closed = True


__all__ = [
    "MANIFEST_ENV",
    "NativeRuntime",
    "WORKER_MODULE",
    "_additional_allow_read",
    "_runner_abort_signal",
]
