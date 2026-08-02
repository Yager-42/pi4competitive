"""O16 — real sandbox broker IPC protocol round trips.

Source: pi-sandbox@0.4.2 ``srt-broker.mjs`` behavior (one init,
initialize/wrap/reset, stdio passthrough, exit 1 on failure).
License: Apache-2.0 (retained under the native sandbox license directory)

Host delta: the broker is spawned directly with a socketpair IPC channel
(the runner does the same); a host with the platform's sandbox deps exercises
the full initialize -> wrap (sandbox-exec / bwrap) -> run -> cleanup -> reset
path. The invocation uses the stdin command transport (argv = [shell],
command bytes arrive on the broker's stdin, piped to the target), matching
the runner's default shell config. The IPC writer stays open until the
broker exits: an early IPC EOF is the parent-disconnect signal that kills
the sandboxed target (and lets the init gate fail instead of waiting).
Linux-specific enforcement stays in the host-gated L-tests.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import sys
from pathlib import Path

import pytest

BROKER_MODULE = (
    Path(__file__).resolve().parents[5]
    / "competitive_app"
    / "src"
    / "competitive_app"
    / "adapter"
    / "out"
    / "sandbox"
    / "native"
    / "broker.py"
)


def _sandbox_deps_available() -> bool:
    """Host-gated: macOS needs sandbox-exec; Linux needs bwrap+socat+rg
    (the manager's dependency gate would fail the broker otherwise)."""
    if sys.platform == "darwin":
        return shutil.which("sandbox-exec") is not None
    if sys.platform == "linux":
        return all(
            shutil.which(tool) is not None for tool in ("bwrap", "socat", "rg")
        )
    return False


requires_sandbox_deps = pytest.mark.skipif(
    not _sandbox_deps_available(),
    reason="host sandbox dependencies unavailable (offline host gate)",
)

WORKSPACE_CONFIG = {
    "filesystem": {
        "denyRead": [],
        "allowRead": [],
        "allowWrite": [],
        "denyWrite": [],
        "allowGitConfig": True,
    },
    "network": {
        "allowedDomains": [],
        "deniedDomains": [],
        "allowLocalBinding": False,
        "allowAllUnixSockets": False,
        "allowUnixSockets": [],
    },
}


async def _spawn_broker(
    tmp_path: Path,
) -> tuple[asyncio.subprocess.Process, socket.socket, asyncio.StreamWriter]:
    ipc_parent, ipc_child = socket.socketpair()
    os.set_inheritable(ipc_child.fileno(), True)
    env = {**os.environ, "PI_SANDBOX_IPC_FD": str(ipc_child.fileno())}
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(BROKER_MODULE),
        cwd=str(tmp_path),
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        pass_fds=(ipc_child.fileno(),),
    )
    ipc_child.close()
    ipc_reader, ipc_writer = await asyncio.open_connection(sock=ipc_parent)
    return proc, ipc_parent, ipc_writer


async def _send_init(writer: asyncio.StreamWriter) -> None:
    init = {
        "type": "init",
        "invocation": ["/bin/bash"],
        "runtimeConfig": WORKSPACE_CONFIG,
    }
    writer.write((json.dumps(init) + "\n").encode())
    await writer.drain()


async def _run_broker_command(
    tmp_path: Path,
    command: str,
) -> tuple[int, str, str]:
    proc, ipc_parent, ipc_writer = await _spawn_broker(tmp_path)
    proc.stdin.write(command.encode())
    await proc.stdin.drain()
    proc.stdin.close()
    await _send_init(ipc_writer)
    out, err = await proc.communicate()
    ipc_writer.close()
    ipc_parent.close()
    return proc.returncode or 0, out.decode(), err.decode()


@requires_sandbox_deps
async def test_broker_runs_a_command_end_to_end(tmp_path) -> None:
    code, out, err = await _run_broker_command(tmp_path, "printf hello-from-sandbox\n")
    assert "hello-from-sandbox" in out, (out, err)
    assert code == 0


@requires_sandbox_deps
async def test_broker_propagates_target_exit_code(tmp_path) -> None:
    code, out, err = await _run_broker_command(tmp_path, "exit 7\n")
    assert code == 7, (out, err)


async def test_broker_rejects_invalid_init_message(tmp_path) -> None:
    proc, ipc_parent, ipc_writer = await _spawn_broker(tmp_path)
    ipc_writer.write((json.dumps({"type": "nonsense"}) + "\n").encode())
    await ipc_writer.drain()
    # IPC EOF is what lets the broker fail its init gate instead of
    # waiting for the first message forever.
    ipc_writer.close()
    out, err = await proc.communicate()
    ipc_parent.close()
    assert proc.returncode == 1
    assert "invalid broker initialization message" in err.decode()


async def test_broker_exits_1_on_missing_init(tmp_path) -> None:
    proc, ipc_parent, ipc_writer = await _spawn_broker(tmp_path)
    ipc_writer.close()
    out, err = await proc.communicate()
    ipc_parent.close()
    assert proc.returncode == 1
    assert "broker failed" in err.decode()
