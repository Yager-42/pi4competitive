"""Run a command through the sandbox broker subprocess (ADAPT).

Source: pi-sandbox@0.4.2 ``src/runner.ts``
Repository: erichll/pi-packages @ 10c8eeb8269ee478ff7383c7e6139301aa9665f9
License: Apache-2.0 (retained under the native sandbox license directory)

Host delta:
- Node ``fork`` (detached child + IPC channel) -> asyncio subprocess with
  ``start_new_session=True`` (own process group) and a full-duplex
  ``socket.socketpair`` IPC channel; the fd number is passed to the broker
  via ``PI_SANDBOX_IPC_FD``.
- ``AbortSignal`` -> ``asyncio.Future`` (done => aborted).
- ``getShellConfig`` lives in @earendil-works/pi-coding-agent (not in the
  port scope): the broker path always uses argv transport with the user's
  shell (default ``/bin/bash``), which is the production behavior.
- Process-tree kill = ``os.killpg(SIGKILL)`` with fallback; timeout and
  abort kill the whole group; the finally clause kills any survivor.
- ``onData``/``onStdout``/``onStderr`` receive ``bytes``.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import inspect
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from .policy import create_default_policy, to_sandbox_runtime_config

_BROKER_MODULE = Path(__file__).with_name("broker.py")

NetworkEndpointView = dict[str, object]


@dataclass
class SandboxCommandOptions:
    command: str
    cwd: str
    env: dict[str, str] | None = None
    signal: asyncio.Future | None = None
    timeout: float | None = None
    on_data: Callable[[bytes], None] | None = None
    on_stdout: Callable[[bytes], None] | None = None
    on_stderr: Callable[[bytes], None] | None = None
    review: Callable[[object], Awaitable[str]] | None = None
    review_domain: Callable[[NetworkEndpointView], Awaitable[str]] | None = None
    policy: dict | None = None
    shell_path: str | None = None
    direct_invocation: dict | None = None
    on_start: Callable[[asyncio.StreamWriter], None] | None = None
    broker: dict | None = None
    platform: str | None = None


def get_shell_config(
    shell_path: str | None = None,
) -> tuple[str, list[str], bool]:
    """Resolve the user shell. ADAPT: upstream ``getShellConfig`` lives in
    @earendil-works/pi-coding-agent (not in the port scope); the default
    shells (bash/zsh/fish) use the *stdin* command transport, which the
    runner test vectors rely on (argv = [shell], command on stdin)."""
    shell = shell_path or os.environ.get("SHELL") or "/bin/bash"
    return shell, [], True


def command_invocation(
    options: SandboxCommandOptions,
) -> tuple[list[str], bool]:
    """The argv the broker runs, plus whether the command arrives on stdin."""
    if options.direct_invocation:
        return (
            [
                str(options.direct_invocation["command"]),
                *[str(arg) for arg in options.direct_invocation.get("args", [])],
            ],
            False,
        )
    shell, args, command_from_stdin = get_shell_config(options.shell_path)
    argv = [shell, *args]
    if not command_from_stdin:
        argv.append(options.command)
    return argv, command_from_stdin


def kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """SIGKILL the broker's whole process group (detached session leader)."""
    if proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


async def spawn_broker(
    options: SandboxCommandOptions,
) -> tuple[asyncio.subprocess.Process, socket.socket]:
    """Spawn the broker with its IPC channel; returns (proc, parent_sock)."""
    broker = options.broker or {
        "module_path": str(_BROKER_MODULE),
        "exec_argv": [],
    }
    ipc_parent, ipc_child = socket.socketpair()
    os.set_inheritable(ipc_child.fileno(), True)
    env = dict(options.env or os.environ)
    env["PI_SANDBOX_IPC_FD"] = str(ipc_child.fileno())
    exec_argv = [str(arg) for arg in broker.get("exec_argv", [])]
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        *exec_argv,
        broker["module_path"],
        cwd=options.cwd,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        pass_fds=(ipc_child.fileno(),),
        start_new_session=True,
    )
    ipc_child.close()
    return proc, ipc_parent


def _is_network_request(value: object) -> bool:
    return (
        isinstance(value, dict)
        and value.get("type") == "network-request"
        and isinstance(value.get("id"), str)
        and isinstance(value.get("hostname"), str)
        and isinstance(value.get("port"), (int, float))
    )


async def answer_network_request(
    writer: asyncio.StreamWriter,
    request: dict,
    options: SandboxCommandOptions,
) -> None:
    """Ask the command-specific reviewer and reply to the broker."""
    action = "deny"
    try:
        if options.review_domain is not None:
            chosen = await options.review_domain(
                {
                    "hostname": request["hostname"],
                    "port": int(request["port"]),
                    "protocol": "tcp",
                }
            )
            action = chosen if chosen in ("allow", "deny") else "deny"
    except Exception as error:  # noqa: BLE001 — upstream logs and denies
        if options.on_data is not None:
            options.on_data(
                (
                    f"pi-sandbox: network approval failed for "
                    f"{request['hostname']}:{request['port']}: {error}\n"
                ).encode()
            )
    if writer.is_closing():
        return
    writer.write(
        (
            json.dumps(
                {"type": "network-response", "id": request["id"], "action": action}
            )
            + "\n"
        ).encode()
    )
    await writer.drain()


async def _ipc_loop(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    options: SandboxCommandOptions,
) -> None:
    while True:
        line = await reader.readline()
        if not line:
            break
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if _is_network_request(message):
            asyncio.create_task(answer_network_request(writer, message, options))


async def run_sandboxed_command(
    options: SandboxCommandOptions,
) -> dict[str, int | None]:
    """Run *options.command* inside the sandbox broker; returns exit code.

    Raises ``RuntimeError`` for unsupported platforms, ``TimeoutError``
    (message ``timeout:<seconds>``) on timeout, and ``asyncio.CancelledError``
    / ``RuntimeError("aborted")`` on abort.
    """
    platform = options.platform or sys.platform
    if platform not in ("linux", "darwin"):
        raise RuntimeError(f"pi-sandbox does not support {platform}")
    if options.signal is not None and options.signal.done():
        raise RuntimeError("aborted")

    invocation, command_from_stdin = command_invocation(options)
    policy = options.policy if options.policy is not None else create_default_policy(
        options.cwd
    )
    broker, ipc_parent = await spawn_broker(options)
    timed_out = False
    timeout_task: asyncio.Task | None = None

    def _on_abort(_fut: asyncio.Future) -> None:
        kill_process_tree(broker)

    ipc_writer: asyncio.StreamWriter | None = None
    try:
        ipc_reader, ipc_writer = await asyncio.open_connection(sock=ipc_parent)
    except Exception:
        ipc_parent.close()
        kill_process_tree(broker)
        await broker.wait()
        raise

    ipc_task = asyncio.create_task(_ipc_loop(ipc_reader, ipc_writer, options))

    async def _send_init() -> None:
        init = {
            "type": "init",
            "invocation": invocation,
            "runtimeConfig": to_sandbox_runtime_config(policy),
        }
        ipc_writer.write((json.dumps(init) + "\n").encode())
        await ipc_writer.drain()

    async def _write_stdin() -> None:
        try:
            if command_from_stdin:
                broker.stdin.write(options.command.encode())
                await broker.stdin.drain()
                broker.stdin.close()
            elif options.direct_invocation and options.on_start is not None:
                # The caller owns EOF (upstream leaves stdin open for onStart).
                options.on_start(broker.stdin)
            else:
                broker.stdin.close()
        except (ConnectionError, OSError):
            pass
    async def _pump(name: str, callback: Callable[[bytes], None] | None) -> None:
        stream = broker.stdout if name == "stdout" else broker.stderr
        while True:
            chunk = await stream.read(65536)
            if not chunk:
                break
            if options.on_data is not None:
                options.on_data(chunk)
            if callback is not None:
                result = callback(chunk)
                if inspect.isawaitable(result):
                    await result

    try:
        try:
            await _send_init()
            await _write_stdin()
        except (ConnectionError, OSError) as error:
            raise RuntimeError(f"broker failed to start: {error}") from error

        abort_callback = None
        if options.signal is not None:
            abort_callback = options.signal.add_done_callback(_on_abort)
        if options.timeout is not None and options.timeout > 0:
            async def _timeout() -> None:
                await asyncio.sleep(options.timeout)
                nonlocal timed_out
                timed_out = True
                kill_process_tree(broker)

            timeout_task = asyncio.create_task(_timeout())

        stdout_task = asyncio.create_task(_pump("stdout", options.on_stdout))
        stderr_task = asyncio.create_task(_pump("stderr", options.on_stderr))

        exit_code = await broker.wait()
        ipc_task.cancel()
        stdout_task.cancel()
        stderr_task.cancel()
        pump_results = await asyncio.gather(
            ipc_task, stdout_task, stderr_task, return_exceptions=True
        )
        # Callback/parse errors raised inside a pump must surface (the
        # worker has already exited; the finally clause cleans up).
        for pump_result in pump_results:
            if isinstance(pump_result, BaseException) and not isinstance(
                pump_result, asyncio.CancelledError
            ):
                raise pump_result

        if options.signal is not None and options.signal.done():
            raise RuntimeError("aborted")
        if timed_out:
            raise TimeoutError(f"timeout:{options.timeout}")
        return {"exit_code": exit_code}
    finally:
        if timeout_task is not None:
            timeout_task.cancel()
        if options.signal is not None and abort_callback is not None:
            options.signal.remove_done_callback(abort_callback)
        if broker.returncode is None:
            kill_process_tree(broker)
        try:
            if ipc_writer is not None:
                ipc_writer.close()
            ipc_parent.close()
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    "SandboxCommandOptions",
    "answer_network_request",
    "command_invocation",
    "get_shell_config",
    "kill_process_tree",
    "run_sandboxed_command",
    "spawn_broker",
]
