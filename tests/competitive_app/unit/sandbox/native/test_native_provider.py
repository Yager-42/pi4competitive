"""O17–O18 — native provider scope lifecycle and runtime IPC/abort/parallel
(NEW-HOST vectors; runner IPC vectors live in test_runner.py).

Required behavior (G0 map §8.1): IPC, timeout/abort/tree cleanup,
independent concurrency, per-scope workspace lifecycle, worker env
allowlist, and scope-abort killing in-flight invocations.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from competitive_app.adapter.out.sandbox.exceptions import (
    SandboxCommandError,
    SandboxPermissionError,
    SandboxRuntimeError,
)
from competitive_app.adapter.out.sandbox.native.native_runtime import (
    MANIFEST_ENV,
    NativeRuntime,
    _additional_allow_read,
)
from competitive_app.adapter.out.sandbox.native.native_sandbox_provider import (
    NATIVE_WORKER_ENVIRONMENT,
    NativeSandboxProvider,
    _worker_environment,
)
from competitive_app.adapter.out.sandbox.protocol import (
    PROTOCOL_VERSION,
    RpcFrame,
    RpcProtocolError,
    RpcRequest,
)
from competitive_app.adapter.out.sandbox.utils import derive_sandbox_id

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FAKE_BROKER = {"module_path": str(FIXTURES / "fake_broker.py"), "exec_argv": []}

SCOPE = derive_sandbox_id("session-native-provider")
OTHER_SCOPE = derive_sandbox_id("session-other")


def _request(scope_id: str = SCOPE, tool_call_id: str = "call-1") -> RpcRequest:
    return RpcRequest(
        protocol_version=PROTOCOL_VERSION,
        scope_id=scope_id,
        tool_call_id=tool_call_id,
        tool_name="echo",
        target={"module": "capability_packages.echo_example.extensions.echo_tools", "qualname": "echo"},
        arguments={"text": "hi"},
    )


def _runtime(workspace: Path, **overrides: Any) -> NativeRuntime:
    Path(workspace).mkdir(parents=True, exist_ok=True)
    invocation = {"command": sys.executable, "args": [str(FIXTURES / "fake_worker.py")]}
    base: dict[str, Any] = {
        "workspace": workspace,
        "env": {"PYTHONPATH": os.pathsep.join(p for p in sys.path if p)},
        "broker": FAKE_BROKER,
        "no_change_timeout": 2.0,
        "worker_invocation": invocation,
    }
    base.update(overrides)
    return NativeRuntime(**base)


async def _execute(runtime: NativeRuntime, **kwargs: Any) -> RpcFrame:
    return await runtime.execute_worker(
        _request(),
        lambda _frame: None,
        command="python -m competitive_app.adapter.out.sandbox.worker",
        **kwargs,
    )


# ------------------------------------------------------------------ provider


@pytest.mark.asyncio
async def test_provider_acquire_creates_workspace_and_returns_singleton(tmp_path: Path) -> None:
    provider = NativeSandboxProvider(sandbox_root=tmp_path / "sandboxes")
    sandbox = await provider.acquire(SCOPE)
    assert sandbox.id == SCOPE
    workspace = tmp_path / "sandboxes" / SCOPE
    assert workspace.is_dir()
    assert await provider.acquire(SCOPE) is sandbox
    await provider.shutdown()


@pytest.mark.asyncio
async def test_provider_release_closes_and_reacquire_rebuilds(tmp_path: Path) -> None:
    provider = NativeSandboxProvider(sandbox_root=tmp_path / "sandboxes")
    first = await provider.acquire(SCOPE)
    await provider.release(SCOPE)
    second = await provider.acquire(SCOPE)
    assert second is not first
    assert (tmp_path / "sandboxes" / SCOPE).is_dir()  # workspace persists
    await provider.shutdown()




@pytest.mark.asyncio
async def test_provider_closes_retained_workspace_and_manifest_fds(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("trusted")
    provider = NativeSandboxProvider(
        sandbox_root=tmp_path / "sandboxes", manifest_path=manifest
    )
    await provider.acquire(SCOPE)
    workspace_fd = provider._workspace_fds[SCOPE]
    manifest_fd = provider._manifest_fds[SCOPE]
    os.fstat(workspace_fd)
    os.fstat(manifest_fd)
    await provider.release(SCOPE)
    with pytest.raises(OSError):
        os.fstat(workspace_fd)
    with pytest.raises(OSError):
        os.fstat(manifest_fd)

@pytest.mark.asyncio
async def test_provider_destroy_aborts_in_flight_invocation(tmp_path: Path) -> None:
    provider = NativeSandboxProvider(sandbox_root=tmp_path / "sandboxes")
    sandbox = await provider.acquire(SCOPE)
    captured: list[asyncio.Future] = []

    def factory(workspace: Path, **kwargs: Any) -> NativeRuntime:
        captured.append(kwargs["scope_signal"])
        return _runtime(workspace, **kwargs)

    provider._runtime_factory = factory  # type: ignore[attr-defined]
    await provider.release(SCOPE)
    sandbox = await provider.acquire(SCOPE)
    assert len(captured) == 1
    signal = captured[-1]
    assert not signal.done()
    await provider.destroy_scope(SCOPE)
    assert signal.done()


@pytest.mark.asyncio
async def test_provider_destroy_preserves_workspace_until_delete(tmp_path: Path) -> None:
    provider = NativeSandboxProvider(sandbox_root=tmp_path / "sandboxes")
    await provider.acquire(SCOPE)
    await provider.destroy_scope(SCOPE)
    assert (tmp_path / "sandboxes" / SCOPE).is_dir()
    await provider.shutdown()


@pytest.mark.asyncio
async def test_provider_rejects_invalid_scope_id(tmp_path: Path) -> None:
    provider = NativeSandboxProvider(sandbox_root=tmp_path / "sandboxes")
    with pytest.raises(ValueError, match="scope id"):
        await provider.acquire("not-a-scope")
    await provider.shutdown()


@pytest.mark.asyncio
async def test_provider_shutdown_aborts_every_scope(tmp_path: Path) -> None:
    provider = NativeSandboxProvider(sandbox_root=tmp_path / "sandboxes")
    await provider.acquire(SCOPE)
    await provider.acquire(OTHER_SCOPE)
    await provider.shutdown()
    with pytest.raises(RuntimeError, match="shut down"):
        await provider.acquire(SCOPE)


def test_worker_environment_allowlists_provider_vars_only() -> None:
    env = _worker_environment(
        {
            "TAVILY_API_KEY": "secret",
            "GROK_MODEL": "grok-x",
            "HOME": "/Users/test",
            "PATH": "/usr/bin",
            "PYTHONPATH": "/repo/src",
            "AWS_SECRET_ACCESS_KEY": "leak",
            "DATABASE_URL": "postgres://leak",
        }
    )
    assert env == {
        "TAVILY_API_KEY": "secret",
        "GROK_MODEL": "grok-x",
        "HOME": "/Users/test",
        "PATH": "/usr/bin",
        "PYTHONPATH": "/repo/src",
    }
    assert all(name in NATIVE_WORKER_ENVIRONMENT for name in env)


def test_worker_environment_drops_unset_and_guarantees_pythonpath(monkeypatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    env = _worker_environment(None)
    assert "TAVILY_API_KEY" not in env
    assert env["PYTHONPATH"]  # sys.path fallback


def test_additional_allow_read_excludes_interpreter_root() -> None:
    roots = _additional_allow_read(
        {"PYTHONPATH": os.pathsep.join([sys.prefix, "/repo/capability_packages", "relative"])}
    )
    assert roots == ["/repo/capability_packages"]


# ------------------------------------------------------------------- runtime


@pytest.mark.asyncio
async def test_runtime_round_trips_frames_through_broker(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "ws")
    frames: list[tuple[str, str]] = []

    async def collect(frame: RpcFrame) -> None:
        frames.append((frame.type, frame.result.get("content", [])[0].get("text", "")))  # type: ignore[index]

    terminal = await runtime.execute_worker(
        _request(),
        collect,
        command="python -m competitive_app.adapter.out.sandbox.worker",
    )
    assert terminal.type == "result"
    assert frames == [("update", "partial"), ("result", "final")]
    assert frames[1][1] == "final"
    await runtime.close()


@pytest.mark.asyncio
async def test_runtime_passes_manifest_env_to_worker(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    runtime = _runtime(tmp_path / "ws", manifest_path=manifest)
    seen: list[str] = []

    async def collect(frame: RpcFrame) -> None:
        if frame.type == "update":
            text = frame.result.get("content", [])[0].get("text", "")  # type: ignore[index]
            seen.append(text)

    terminal = await runtime.execute_worker(
        _request(),
        collect,
        command="python -m competitive_app.adapter.out.sandbox.worker",
    )
    assert terminal.type == "result"
    assert seen == [f"partial manifest={manifest}"]
    await runtime.close()


@pytest.mark.asyncio
async def test_runtime_worker_exit_without_frames_raises_command_error(tmp_path: Path) -> None:
    runtime = _runtime(
        tmp_path / "ws",
        env={"PYTHONPATH": os.pathsep.join(p for p in sys.path if p), "FAKE_WORKER_EXIT": "7"},
    )
    with pytest.raises(SandboxCommandError, match="without a terminal frame") as error:
        await _execute(runtime)
    assert error.value.details["exit_code"] == 7
    await runtime.close()


@pytest.mark.asyncio
async def test_runtime_identity_mismatch_raises_protocol_error(tmp_path: Path) -> None:
    runtime = _runtime(
        tmp_path / "ws",
        env={"PYTHONPATH": os.pathsep.join(p for p in sys.path if p), "FAKE_WORKER_BAD_SCOPE": "1"},
    )
    with pytest.raises(RpcProtocolError, match="identity does not match"):
        await _execute(runtime)
    await runtime.close()


@pytest.mark.asyncio
async def test_runtime_worker_silent_exit_raises_missing_final(tmp_path: Path) -> None:
    runtime = _runtime(
        tmp_path / "ws",
        env={"PYTHONPATH": os.pathsep.join(p for p in sys.path if p), "FAKE_WORKER_EMPTY": "1"},
    )
    with pytest.raises(RpcProtocolError, match="stream ended without a terminal frame"):
        await _execute(runtime)
    await runtime.close()


@pytest.mark.asyncio
async def test_runtime_no_output_timeout_raises_runtime_error(tmp_path: Path) -> None:
    runtime = _runtime(
        tmp_path / "ws",
        env={"PYTHONPATH": os.pathsep.join(p for p in sys.path if p), "FAKE_WORKER_SLEEP": "1"},
        no_change_timeout=0.1,
    )
    with pytest.raises(SandboxRuntimeError, match="no output"):
        await _execute(runtime)
    await runtime.close()


@pytest.mark.asyncio
async def test_runtime_aborts_on_call_signal(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "ws")

    class _Abort:
        aborted = True

        def addEventListener(self, _event: str, _callback: Any) -> None:
            pass

    with pytest.raises(asyncio.CancelledError, match="aborted"):
        await _execute(runtime, signal=_Abort())
    await runtime.close()


@pytest.mark.asyncio
async def test_runtime_aborts_when_scope_signal_fires(tmp_path: Path) -> None:
    loop = asyncio.get_running_loop()
    signal = loop.create_future()

    async def run() -> None:
        runtime = _runtime(tmp_path / "ws", scope_signal=signal)
        signal.set_result(None)
        with pytest.raises(asyncio.CancelledError, match="aborted"):
            await _execute(runtime)
        await runtime.close()

    await run()


@pytest.mark.asyncio
async def test_runtime_closed_rejects_execution(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "ws")
    await runtime.close()
    with pytest.raises(SandboxRuntimeError, match="closed"):
        await _execute(runtime)



@pytest.mark.asyncio
async def test_runtime_rejects_workspace_replacement_before_spawn(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime = _runtime(workspace)
    moved = tmp_path / "moved"
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace.rename(moved)
    workspace.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(SandboxRuntimeError, match="workspace"):
            await _execute(runtime)
        assert not (outside / "approved_tools.json").exists()
    finally:
        await runtime.close()

@pytest.mark.asyncio
async def test_runtime_independent_concurrent_scopes(tmp_path: Path) -> None:
    async def one(scope_id: str, tag: str) -> str:
        runtime = _runtime(tmp_path / tag)
        terminal = await runtime.execute_worker(
            _request(scope_id=scope_id, tool_call_id=f"call-{tag}"),
            lambda _frame: None,
            command="python -m competitive_app.adapter.out.sandbox.worker",
        )
        await runtime.close()
        return str(terminal.result.get("content", [])[0].get("text", ""))  # type: ignore[index]

    results = await asyncio.gather(
        one(SCOPE, "alpha"), one(OTHER_SCOPE, "beta"), one(derive_sandbox_id("session-gamma"), "gamma")
    )
    assert results == ["final", "final", "final"]
