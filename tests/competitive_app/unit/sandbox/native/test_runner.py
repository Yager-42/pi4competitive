"""O16 — runner IPC, network review routing, timeout, abort, and independent
concurrency (PORT of pi-sandbox runner.test.ts with the fake broker fixture).

Source: pi-sandbox@0.4.2 ``runner.test.ts`` + ``test/fixtures/srt-broker.mjs``
License: Apache-2.0 (retained under the native sandbox license directory)

Host delta: the fake broker is a Python fixture speaking the JSON-lines IPC
protocol over the runner-provided socketpair.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

from competitive_app.adapter.out.sandbox.native.runner import (
    SandboxCommandOptions,
    command_invocation,
    run_sandboxed_command,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FAKE_BROKER = {"module_path": str(FIXTURES / "fake_broker.py"), "exec_argv": []}


def _options(**overrides: object) -> SandboxCommandOptions:
    base: dict[str, object] = {
        "command": "printf broker-ok",
        "cwd": str(FIXTURES.parent),
        "broker": FAKE_BROKER,
        "on_data": lambda data: None,
    }
    base.update(overrides)
    return SandboxCommandOptions(**base)


def test_executes_a_command_through_the_isolated_broker() -> None:
    output: list[str] = []
    reviews = 0

    async def review(_trap: object) -> str:
        nonlocal reviews
        reviews += 1
        return "allow"

    result = asyncio.run(
        run_sandboxed_command(
            _options(
                on_data=lambda data: output.append(data.decode()),
                review=review,
            )
        )
    )
    assert result["exit_code"] == 0
    assert "".join(output) == "broker-ok"
    assert reviews == 0


def test_routes_network_requests_to_the_command_specific_reviewer() -> None:
    endpoints: list[str] = []
    env = {
        **os.environ,
        "FAKE_SRT_NETWORK_HOST": "api.example.com",
        "FAKE_SRT_NETWORK_PORT": "8443",
    }

    async def review_domain(endpoint: dict) -> str:
        endpoints.append(f"{endpoint['hostname']}:{endpoint['port']}")
        return "allow"

    result = asyncio.run(
        run_sandboxed_command(
            _options(
                command="printf network-ok",
                env=env,
                review_domain=review_domain,
            )
        )
    )
    assert result["exit_code"] == 0
    assert endpoints == ["api.example.com:8443"]


def test_fails_closed_when_a_network_request_is_denied() -> None:
    env = {**os.environ, "FAKE_SRT_NETWORK_HOST": "api.example.com"}

    async def review_domain(_endpoint: dict) -> str:
        return "deny"

    result = asyncio.run(
        run_sandboxed_command(
            _options(command="printf should-not-run", env=env, review_domain=review_domain)
        )
    )
    assert result["exit_code"] != 0


def test_review_domain_failure_logs_and_denies() -> None:
    env = {**os.environ, "FAKE_SRT_NETWORK_HOST": "api.example.com"}
    output: list[str] = []

    async def review_domain(_endpoint: dict) -> str:
        raise RuntimeError("approval service down")

    result = asyncio.run(
        run_sandboxed_command(
            _options(
                command="printf x",
                env=env,
                review_domain=review_domain,
                on_data=lambda data: output.append(data.decode()),
            )
        )
    )
    assert result["exit_code"] != 0
    assert any("network approval failed" in line for line in output)


def test_kills_the_sandboxed_process_tree_on_timeout() -> None:
    started = time.monotonic()

    async def run() -> None:
        with pytest.raises(TimeoutError, match=r"timeout:0\.05"):
            await run_sandboxed_command(
                _options(command="sleep 5", timeout=0.05)
            )

    asyncio.run(run())
    assert time.monotonic() - started < 5.0


def test_abort_signal_kills_the_process_tree() -> None:
    async def run() -> None:
        signal = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(
            run_sandboxed_command(
                _options(command="sleep 5", signal=signal)
            )
        )
        await asyncio.sleep(0.3)
        signal.set_result(None)
        with pytest.raises(RuntimeError, match="aborted"):
            await task

    asyncio.run(run())


def test_supports_a_persistent_direct_invocation() -> None:
    worker = FIXTURES / "echo_worker.py"
    output: list[str] = []

    def on_start(stdin) -> None:
        stdin.write(b"rpc-ok")
        stdin.write_eof()

    result = asyncio.run(
        run_sandboxed_command(
            _options(
                command="direct invocation fixture",
                direct_invocation={"command": sys.executable, "args": [str(worker)]},
                on_start=on_start,
                on_data=lambda data: output.append(data.decode()),
            )
        )
    )
    assert result["exit_code"] == 0
    assert "".join(output) == "rpc-ok"


def test_independent_concurrent_invocations() -> None:
    async def run() -> list[dict]:
        async def one(tag: str) -> dict:
            output: list[str] = []

            def collect(data: bytes) -> None:
                output.append(data.decode())

            result = await run_sandboxed_command(
                _options(command=f"printf {tag}", on_data=collect)
            )
            return {"exit_code": result["exit_code"], "output": "".join(output)}

        return await asyncio.gather(one("alpha"), one("beta"), one("gamma"))

    results = asyncio.run(run())
    assert [r["output"] for r in results] == ["alpha", "beta", "gamma"]
    assert all(r["exit_code"] == 0 for r in results)


def test_unsupported_platform_raises() -> None:
    with pytest.raises(RuntimeError, match="does not support"):
        asyncio.run(run_sandboxed_command(_options(platform="win32")))


def test_command_invocation_shapes() -> None:
    argv, from_stdin = command_invocation(
        SandboxCommandOptions(command="echo hi", cwd="/tmp")
    )
    assert argv == [os.environ.get("SHELL", "/bin/bash")]
    assert from_stdin is True

    argv2, from_stdin2 = command_invocation(
        SandboxCommandOptions(
            command="x",
            cwd="/tmp",
            direct_invocation={"command": "/usr/bin/env", "args": ["-i"]},
        )
    )
    assert argv2 == ["/usr/bin/env", "-i"]
    assert from_stdin2 is False
