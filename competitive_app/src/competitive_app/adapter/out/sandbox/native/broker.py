"""Sandbox broker subprocess (ADAPT of pi-sandbox ``src/srt-broker.mjs``).

Source: pi-sandbox@0.4.2 ``src/srt-broker.mjs``
Repository: erichll/pi-packages @ 10c8eeb8269ee478ff7383c7e6139301aa9665f9
License: Apache-2.0 (retained under the native sandbox license directory)

Host delta:
- Node ``fork`` IPC channel is replaced by a full-duplex ``socket.socketpair``
  passed as an inherited fd; the fd number arrives via ``PI_SANDBOX_IPC_FD``
  (set by the runner). Protocol is unchanged JSON messages, one per line.
- ``SandboxManager.wrapWithSandboxArgv`` returns argv only in the Python
  port (env is baked into the argv via bwrap ``--setenv`` / ``env``), so
  the target inherits the broker's environment.
- asyncio subprocess + stream pumps replace Node stream piping; behavior
  (one init, initialize/wrap/reset, stdio passthrough, exit 1 on failure,
  parent-disconnect kills the target) is preserved.
- The broker's own ``shellQuote`` (always single-quote wrapping, ``'\\''``
  escaping) is ported exactly; it is intentionally NOT the SRT shell-quote.
"""
from __future__ import annotations
import asyncio
import json
import os
import socket
import stat
import sys
import uuid

if __package__ in (None, ""):
    # The runner forks this module by path (Node-fork parity); bootstrap the
    # package so the relative imports below resolve like ``python -m ...``.
    _src_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)
        ))))
    )
    if _src_root not in sys.path:
        sys.path.insert(0, _src_root)
    __package__ = "competitive_app.adapter.out.sandbox.native"

from .network_policy import validate_public_hostname
from .srt import manager as SandboxManager


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _is_init_message(value: object) -> bool:
    return (
        isinstance(value, dict)
        and value.get("type") == "init"
        and isinstance(value.get("invocation"), list)
        and len(value["invocation"]) > 0
        and all(isinstance(item, str) for item in value["invocation"])
        and isinstance(value.get("runtimeConfig"), dict)
    )


def _is_network_response(value: object) -> bool:
    return (
        isinstance(value, dict)
        and value.get("type") == "network-response"
        and isinstance(value.get("id"), str)
        and value.get("action") in ("allow", "deny")
    )


async def _ask_network(
    hostname: str,
    port: int,
    writer: asyncio.StreamWriter,
    pending: dict[str, asyncio.Future],
) -> bool:
    """Ask the parent runner whether the sandboxed target may connect."""
    if writer.is_closing():
        return False
    normalized = await validate_public_hostname(hostname)
    if not normalized:
        return False
    request_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    pending[request_id] = future
    try:
        writer.write(
            (
                json.dumps(
                    {
                        "type": "network-request",
                        "id": request_id,
                        "hostname": normalized,
                        "port": port,
                    }
                )
                + "\n"
            ).encode()
        )
        await writer.drain()
        allowed = bool(await future)
        if not allowed:
            return False
        # Re-resolve immediately before the proxy dials.  Approval must not
        # turn a hostname that has since rebound to a private address into a
        # permitted connection.
        return (await validate_public_hostname(normalized)) is not None
    finally:
        pending.pop(request_id, None)


async def _pump_stdin_to_target(
    stdin_reader: asyncio.StreamReader,
    target_stdin: asyncio.StreamWriter,
) -> None:
    try:
        while True:
            chunk = await stdin_reader.read(65536)
            if not chunk:
                break
            target_stdin.write(chunk)
            await target_stdin.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            target_stdin.write_eof()
        except (ConnectionError, OSError):
            pass


async def _pump_stream(
    src: asyncio.StreamReader,
    dst,
) -> None:
    """Pump a target stream to the broker's stdout/stderr."""
    while True:
        chunk = await src.read(65536)
        if not chunk:
            break
        dst.write(chunk)
        dst.flush()


def _adopt_workspace_descriptor() -> int | None:
    raw_fd = os.environ.get("PI_SANDBOX_WORKSPACE_FD")
    if raw_fd is None:
        return None
    descriptor = int(raw_fd)
    path = os.environ.get("PI_SANDBOX_WORKSPACE_PATH")
    if not path:
        raise RuntimeError("workspace descriptor path is missing")
    fd_stat = os.fstat(descriptor)
    path_stat = os.stat(path, follow_symlinks=False)
    if not stat.S_ISDIR(fd_stat.st_mode) or not stat.S_ISDIR(path_stat.st_mode):
        raise RuntimeError("workspace descriptor is not a directory")
    if (fd_stat.st_dev, fd_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
        raise RuntimeError("workspace changed during broker handoff")
    os.fchdir(descriptor)
    return descriptor


async def _main() -> int:
    workspace_fd = _adopt_workspace_descriptor()
    manifest_fd_raw = os.environ.get("PI4COMPETITIVE_MANIFEST_FD")
    manifest_fd = int(manifest_fd_raw) if manifest_fd_raw is not None else None
    ipc_fd = int(os.environ["PI_SANDBOX_IPC_FD"])
    sock = socket.socket(fileno=ipc_fd)
    ipc_reader, ipc_writer = await asyncio.open_connection(sock=sock)
    pending_network: dict[str, asyncio.Future] = {}
    target: asyncio.subprocess.Process | None = None
    disconnect_event = asyncio.Event()

    async def _ipc_loop() -> None:
        """Consume network-response messages; parent EOF kills the target."""
        try:
            while True:
                line = await ipc_reader.readline()
                if not line:
                    break
                message = json.loads(line)
                if _is_network_response(message):
                    future = pending_network.get(message["id"])
                    if future is not None and not future.done():
                        future.set_result(message["action"] == "allow")
        except (json.JSONDecodeError, ConnectionError, OSError):
            pass
        finally:
            if target is not None and target.returncode is None:
                try:
                    target.kill()
                except ProcessLookupError:
                    pass
            disconnect_event.set()

    # First message must be the init message (upstream `once(process, "message")`).
    init_line = await ipc_reader.readline()
    if not init_line:
        raise ValueError("received no broker initialization message")
    try:
        init_message = json.loads(init_line)
    except json.JSONDecodeError as error:
        raise ValueError("received an invalid broker initialization message") from error
    if not _is_init_message(init_message):
        raise ValueError("received an invalid broker initialization message")

    loop = asyncio.get_running_loop()

    async def _ask_callback(request: dict) -> bool:
        return await _ask_network(
            request.get("host", ""),
            request.get("port") or 443,
            ipc_writer,
            pending_network,
        )

    await SandboxManager.initialize(
        init_message["runtimeConfig"], _ask_callback, False
    )
    command = " ".join(_shell_quote(arg) for arg in init_message["invocation"])
    manifest_path = os.environ.get("PI4COMPETITIVE_MANIFEST_PATH")
    linux_fd_bindings: list[tuple[int, str, bool]] = []
    if sys.platform.startswith("linux") and manifest_fd is not None:
        if not manifest_path:
            raise RuntimeError("manifest descriptor path is missing")
        linux_fd_bindings.append((manifest_fd, manifest_path, True))
    wrapped = await SandboxManager.wrap_with_sandbox(
        command,
        "/bin/bash",
        None,
        None,
        os.getcwd(),
        linux_fd_bindings=linux_fd_bindings,
    )

    target_env = dict(os.environ)
    target_env.pop("PI_SANDBOX_IPC_FD", None)
    target_env.pop("PI_SANDBOX_WORKSPACE_FD", None)
    target_env.pop("PI_SANDBOX_WORKSPACE_PATH", None)
    if sys.platform.startswith("linux"):
        # bwrap exposes the pinned manifest descriptor at manifest_path.  The
        # command itself must use that read-only path because bwrap closes the
        # setup descriptor before exec.
        target_env.pop("PI4COMPETITIVE_MANIFEST_FD", None)
    target_pass_fds = (manifest_fd,) if manifest_fd is not None else ()
    target = await asyncio.create_subprocess_exec(
        *wrapped,
        cwd=None if workspace_fd is not None else os.getcwd(),
        env=target_env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        pass_fds=target_pass_fds,
    )

    ipc_task = asyncio.create_task(_ipc_loop())

    stdin_reader = asyncio.StreamReader()
    stdin_protocol = asyncio.StreamReaderProtocol(stdin_reader)
    await loop.connect_read_pipe(lambda: stdin_protocol, sys.stdin.buffer)
    stdin_task = asyncio.create_task(
        _pump_stdin_to_target(stdin_reader, target.stdin)
    )
    stdout_task = asyncio.create_task(_pump_stream(target.stdout, sys.stdout.buffer))
    stderr_task = asyncio.create_task(_pump_stream(target.stderr, sys.stderr.buffer))

    exit_code = await target.wait()
    stdin_task.cancel()
    stdout_task.cancel()
    stderr_task.cancel()
    ipc_task.cancel()
    try:
        await asyncio.gather(
            stdin_task, stdout_task, stderr_task, ipc_task, return_exceptions=True
        )
    except Exception:  # noqa: BLE001 — cleanup-only
        pass
    SandboxManager.cleanup_after_command()
    await SandboxManager.reset()
    try:
        ipc_writer.close()
    except Exception:  # noqa: BLE001
        pass
    return exit_code if exit_code is not None else 1


def main() -> int:
    try:
        return asyncio.run(_main())
    except Exception as error:  # noqa: BLE001 — upstream catch-all
        sys.stderr.write(
            f"pi-sandbox: Sandbox Runtime broker failed: {error}\n"
        )
        try:
            asyncio.run(SandboxManager.reset())
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
