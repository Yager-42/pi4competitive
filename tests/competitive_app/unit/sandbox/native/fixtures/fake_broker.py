"""Fake sandbox broker fixture (PORT of pi-sandbox test/fixtures/srt-broker.mjs).

Source: pi-sandbox@0.4.2 ``test/fixtures/srt-broker.mjs``
Repository: erichll/pi-packages @ 10c8eeb8269ee478ff7383c7e6139301aa9665f9
License: Apache-2.0 (retained under the native sandbox license directory)

Behavior parity with the Node fixture:
- reads the init message (JSON line over the IPC socket), spawns
  ``invocation`` with the fixture's cwd/env, pipes stdio;
- when ``FAKE_SRT_NETWORK_HOST`` is set, sends a network-request first and
  only starts the target after an ``allow`` response (``deny`` -> stderr
  note + exit 1);
- exits with the target's exit code.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys


async def _main() -> int:
    ipc_fd = int(os.environ["PI_SANDBOX_IPC_FD"])
    sock = socket.socket(fileno=ipc_fd)
    reader, writer = await asyncio.open_connection(sock=sock)

    line = await reader.readline()
    if not line:
        return 1
    init = json.loads(line)
    if os.environ.get("FAKE_SRT_NETWORK_HOST"):
        writer.write(
            (
                json.dumps(
                    {
                        "type": "network-request",
                        "id": "fake-network-request",
                        "hostname": os.environ["FAKE_SRT_NETWORK_HOST"],
                        "port": int(os.environ.get("FAKE_SRT_NETWORK_PORT", "443")),
                    }
                )
                + "\n"
            ).encode()
        )
        await writer.drain()
        response = json.loads(await reader.readline())
        if response.get("action") != "allow":
            sys.stderr.write("fake broker: network denied\n")
            return 1

    proc = await asyncio.create_subprocess_exec(
        *init["invocation"],
        cwd=os.getcwd(),
        env=os.environ,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _pump(src, dst) -> None:
        while True:
            chunk = await src.read(65536)
            if not chunk:
                break
            dst.write(chunk)
            dst.flush()

    async def _stdin_to_target() -> None:
        while True:
            chunk = sys.stdin.buffer.read(65536)
            if not chunk:
                break
            proc.stdin.write(chunk)
            await proc.stdin.drain()
        try:
            proc.stdin.write_eof()
        except (ConnectionError, OSError):
            pass

    stdin_task = asyncio.create_task(_stdin_to_target())
    stdout_task = asyncio.create_task(_pump(proc.stdout, sys.stdout.buffer))
    stderr_task = asyncio.create_task(_pump(proc.stderr, sys.stderr.buffer))
    exit_code = await proc.wait()
    stdin_task.cancel()
    stdout_task.cancel()
    stderr_task.cancel()
    return exit_code if exit_code is not None else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
