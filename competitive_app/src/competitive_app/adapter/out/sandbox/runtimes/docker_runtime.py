"""Async ``agent-sandbox`` carrier for the fixed JSONL worker.

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/sandbox/runtimes/docker_runtime.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see deploy/tool-sandbox/licenses/POIROT-MIT.txt)
Host delta: one AsyncSandbox bash session per AgentTool call and offset-based
long polling; synchronous SDK, file facade, and global command locks omitted.
"""
from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from agent_sandbox import AsyncSandbox

from ..exceptions import SandboxCommandError, SandboxRuntimeError
from ..protocol import (
    FrameSequence,
    RpcFrame,
    RpcProtocolError,
    RpcRequest,
    decode_frame,
    encode_request,
)
from ..types import NO_CHANGE_TIMEOUT_SECONDS, REQUEST_TIMEOUT_SECONDS

FrameCallback = Callable[[RpcFrame], Awaitable[None] | None]


class DockerRuntime:
    """Run one fixed worker process per request through the AIO bash API."""

    def __init__(
        self,
        sandbox_url: str,
        *,
        client: Any | None = None,
        client_factory: Callable[..., Any] = AsyncSandbox,
    ) -> None:
        if not sandbox_url:
            raise ValueError("sandbox URL must be non-empty")
        self._url = sandbox_url.rstrip("/")
        self._client = client or client_factory(
            base_url=self._url,
            timeout=float(REQUEST_TIMEOUT_SECONDS),
        )
        self._active: dict[str, str] = {}
        self._closed = False
        self._close_lock = asyncio.Lock()

    async def execute_worker(
        self,
        request: RpcRequest,
        on_frame: FrameCallback,
        *,
        command: str,
    ) -> RpcFrame:
        if self._closed:
            raise SandboxRuntimeError("sandbox runtime is closed")
        if not command or "\n" in command or "\r" in command:
            raise SandboxRuntimeError("sandbox worker command is invalid")
        payload = encode_request(request).decode("utf-8") + "\n"
        bash = self._client.bash
        session_id: str | None = None
        command_id: str | None = None
        try:
            started = await bash.exec(
                command=command,
                async_mode=True,
                max_output_length=0,
            )
            started_data = _unwrap_data(started)
            session_id = _required_string(started_data, "session_id")
            command_id = _required_string(started_data, "command_id")
            self._active[session_id] = command_id
            await bash.write(session_id=session_id, command_id=command_id, input=payload)
            terminal = await self._poll_output(
                bash,
                request,
                on_frame,
                session_id=session_id,
                command_id=command_id,
                initial=started_data,
            )
            return terminal
        except RpcProtocolError:
            raise
        except SandboxRuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SandboxRuntimeError("sandbox worker runtime request failed") from exc
        finally:
            if session_id is not None:
                self._active.pop(session_id, None)
                await self._close_session_best_effort(bash, session_id)

    async def _poll_output(
        self,
        bash: Any,
        request: RpcRequest,
        on_frame: FrameCallback,
        *,
        session_id: str,
        command_id: str,
        initial: Any,
    ) -> RpcFrame:
        sequence = FrameSequence()
        stdout_offset = _offset(initial, "offset")
        stderr_offset = _offset(initial, "stderr_offset")
        pending = ""
        terminal: RpcFrame | None = None
        diagnostic = ""
        loop = asyncio.get_running_loop()
        last_output = loop.time()

        async def consume(text: str) -> None:
            nonlocal pending, terminal, last_output
            if not text:
                return
            last_output = loop.time()
            pending += text
            lines = pending.split("\n")
            pending = lines.pop()
            for line in lines:
                if not line.strip():
                    continue
                frame = decode_frame(line)
                if frame.scope_id != request.scope_id or frame.tool_call_id != request.tool_call_id:
                    raise RpcProtocolError("worker frame identity does not match request", code="identity_mismatch")
                sequence.accept(frame)
                callback_result = on_frame(frame)
                if inspect.isawaitable(callback_result):
                    await callback_result
                if frame.is_final:
                    terminal = frame
                    return

        initial_stdout = getattr(initial, "stdout", None)
        if initial_stdout:
            await consume(str(initial_stdout))
        initial_stderr = getattr(initial, "stderr", None)
        if initial_stderr:
            diagnostic = _bound_diagnostic(diagnostic + str(initial_stderr))

        while terminal is None:
            if loop.time() - last_output >= NO_CHANGE_TIMEOUT_SECONDS:
                raise SandboxRuntimeError("sandbox worker produced no output before timeout")
            output = await bash.output(
                session_id=session_id,
                command_id=command_id,
                offset=stdout_offset,
                stderr_offset=stderr_offset,
                wait=True,
                wait_timeout=min(4.0, float(REQUEST_TIMEOUT_SECONDS)),
            )
            data = _unwrap_data(output)
            stdout = getattr(data, "stdout", None)
            stderr = getattr(data, "stderr", None)
            if stdout:
                await consume(str(stdout))
            if stderr:
                diagnostic = _bound_diagnostic(diagnostic + str(stderr))
            stdout_offset = _offset(data, "offset", fallback=stdout_offset)
            stderr_offset = _offset(data, "stderr_offset", fallback=stderr_offset)
            status = str(getattr(getattr(data, "command", None), "status", "") or "")
            if terminal is None and status in {"completed", "timed_out", "killed"}:
                # A worker that exits without a terminal frame is a protocol
                # failure, not a successful empty result.
                if pending.strip():
                    raise RpcProtocolError("worker emitted an incomplete frame", code="invalid_json")
                raise SandboxCommandError(
                    "sandbox worker exited without a terminal frame",
                    command="python -m competitive_app.adapter.out.sandbox.worker",
                    exit_code=getattr(getattr(data, "command", None), "exit_code", None),
                )

        sequence.finish()
        return terminal

    async def _close_session_best_effort(self, bash: Any, session_id: str) -> None:
        try:
            await bash.close_session(session_id)
        except Exception:  # noqa: BLE001
            return

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            active = list(self._active.items())
            bash = self._client.bash
            await asyncio.gather(
                *(self._kill_session_best_effort(bash, session_id) for session_id, _ in active),
                return_exceptions=True,
            )
            self._active.clear()
            await _close_sdk_client(self._client)

    async def _kill_session_best_effort(self, bash: Any, session_id: str) -> None:
        try:
            await bash.kill(session_id=session_id, signal="SIGTERM")
        except Exception:  # noqa: BLE001
            return
        finally:
            await self._close_session_best_effort(bash, session_id)


def _unwrap_data(value: Any) -> Any:
    data = getattr(value, "data", None)
    return data if data is not None else value


def _required_string(value: Any, name: str) -> str:
    result = getattr(value, name, None)
    if not isinstance(result, str) or not result:
        raise SandboxRuntimeError(f"sandbox SDK response omitted {name}")
    return result


def _offset(value: Any, name: str, fallback: int = 0) -> int:
    raw = getattr(value, name, None)
    return raw if isinstance(raw, int) and raw >= 0 else fallback


def _bound_diagnostic(value: str) -> str:
    return value[-10_000:]


async def _close_sdk_client(client: Any) -> None:
    direct = getattr(client, "aclose", None)
    if callable(direct):
        result = direct()
        if inspect.isawaitable(result):
            await result
        return
    wrapper_client = getattr(getattr(client, "_client_wrapper", None), "httpx_client", None)
    underlying = getattr(wrapper_client, "httpx_client", wrapper_client)
    for name in ("aclose", "close"):
        closer = getattr(underlying, name, None)
        if not callable(closer):
            continue
        result = closer()
        if inspect.isawaitable(result):
            await result
        return


__all__ = ["DockerRuntime"]
