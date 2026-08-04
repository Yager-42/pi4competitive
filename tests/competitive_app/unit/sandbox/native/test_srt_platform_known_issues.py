"""Focused regressions for SRT Linux/macOS platform helpers."""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

import pytest

from competitive_app.adapter.out.sandbox.native.srt import linux as srt_linux
from competitive_app.adapter.out.sandbox.native.srt import process as srt_process
from competitive_app.adapter.out.sandbox.native.srt import seccomp
from competitive_app.adapter.out.sandbox.native.srt.linux import generate_filesystem_args
from competitive_app.adapter.out.sandbox.native.srt.macos import (
    start_macos_sandbox_log_monitor,
    wrap_command_with_sandbox_macos,
)
from competitive_app.adapter.out.sandbox.native.srt.policy import expand_glob_pattern


def test_linux_socat_listener_uses_private_mode() -> None:
    args = srt_linux._bridge_socat_args("/tmp/http.sock", 3128)
    assert args[0] == "UNIX-LISTEN:/tmp/http.sock,fork,reuseaddr,mode=0600"


def test_linux_equal_deny_write_reapplies_deny_read_tmpfs(tmp_path: Path) -> None:
    denied = tmp_path / "denied"
    denied.mkdir()
    args = asyncio.run(
        generate_filesystem_args(
            {"denyOnly": [str(denied)]},
            {"allowOnly": [str(denied)], "denyWithinAllow": [str(denied)]},
            cwd=str(tmp_path),
        )
    )
    # The initial tmpfs is followed by the denyWrite ro-bind; equality must
    # trigger a second tmpfs mount so the bind cannot expose denied contents.
    tmpfs_indices = [i for i, value in enumerate(args) if value == "--tmpfs"]
    assert len(tmpfs_indices) >= 2
    ro_bind = [
        i
        for i in range(len(args) - 2)
        if args[i] == "--ro-bind" and args[i + 1] == str(denied)
        and args[i + 2] == str(denied)
    ]
    assert ro_bind
    assert tmpfs_indices[-1] > ro_bind[-1]


def test_macos_fast_path_honors_bin_shell() -> None:
    shell = os.path.realpath("/bin/sh") if os.path.exists("/bin/sh") else "sh"
    argv = wrap_command_with_sandbox_macos(
        command="printf '%s' ok",
        needs_network_restriction=False,
        bin_shell="sh",
    )
    assert argv == [shell, "-c", "printf '%s' ok"]


@pytest.mark.asyncio
async def test_macos_monitor_stop_before_task_start(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeProcess:
        def __init__(self) -> None:
            self.stdout = asyncio.StreamReader()
            self.stderr = asyncio.StreamReader()
            self.returncode: int | None = None
            self.terminated = False

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = 0

    process = _FakeProcess()

    async def _spawn(*_args, **_kwargs):
        await asyncio.sleep(0)
        return process

    monkeypatch.setattr(
        "competitive_app.adapter.out.sandbox.native.srt.macos.asyncio.create_subprocess_exec",
        _spawn,
    )
    stop = start_macos_sandbox_log_monitor(lambda _event: None)
    stop()
    await asyncio.sleep(0.05)
    assert process.terminated


def test_policy_glob_expansion_returns_matching_paths(tmp_path: Path) -> None:
    (tmp_path / "a.env").write_text("x")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "b.env").write_text("x")
    matches = expand_glob_pattern(str(tmp_path / "**" / "*.env"))
    assert set(matches) == {str(tmp_path / "a.env"), str(tmp_path / "nested" / "b.env")}


class _FakeProcess:
    def __init__(self, returncode: int | None, done: bool = True) -> None:
        self.returncode = returncode
        self.killed = False
        self._done = done
        self._release = asyncio.Event()

    async def communicate(self) -> tuple[bytes, bytes]:
        if not self._done:
            await self._release.wait()
        return b"", b""

    async def wait(self) -> int:
        if not self._done:
            await self._release.wait()
        if self.returncode is None:
            self.returncode = -9 if self.killed else 0
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self._done = True
        self._release.set()


@pytest.mark.asyncio
async def test_ripgrep_negative_returncode_remains_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(-9)

    async def _spawn(*_args, **_kwargs):
        return process

    monkeypatch.setattr(srt_process.asyncio, "create_subprocess_exec", _spawn)
    with pytest.raises(RuntimeError, match="exit code -9"):
        await srt_process.ripgrep([], ".")


@pytest.mark.asyncio
async def test_ripgrep_cancels_abort_task_when_wait_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(0)
    created: list[asyncio.Future] = []
    real_ensure = srt_process.asyncio.ensure_future

    async def _spawn(*_args, **_kwargs):
        return process

    def _track(awaitable):
        task = real_ensure(awaitable)
        created.append(task)
        return task

    monkeypatch.setattr(srt_process.asyncio, "create_subprocess_exec", _spawn)
    monkeypatch.setattr(srt_process.asyncio, "ensure_future", _track)
    abort_signal = asyncio.get_running_loop().create_future()
    assert await srt_process.ripgrep([], ".", abort_signal) == []
    assert len(created) == 2
    assert all(task.done() for task in created)
    assert created[1].cancelled()


@pytest.mark.asyncio
async def test_ripgrep_cancels_wait_task_when_abort_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(None, done=False)
    created: list[asyncio.Future] = []
    real_ensure = srt_process.asyncio.ensure_future

    async def _spawn(*_args, **_kwargs):
        return process

    def _track(awaitable):
        task = real_ensure(awaitable)
        created.append(task)
        return task

    monkeypatch.setattr(srt_process.asyncio, "create_subprocess_exec", _spawn)
    monkeypatch.setattr(srt_process.asyncio, "ensure_future", _track)
    abort_signal = asyncio.get_running_loop().create_future()
    abort_signal.set_result(None)
    with pytest.raises(asyncio.CancelledError, match="aborted"):
        await srt_process.ripgrep([], ".", abort_signal)
    assert len(created) == 2
    assert all(task.done() for task in created)
    assert process.killed


def test_seccomp_override_uses_host_architecture_and_exec_bit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(seccomp.platform, "machine", lambda: "aarch64")
    payload = b"host-arm64-helper"
    monkeypatch.setitem(seccomp.APPLY_SECCOMP_SHA256, "arm64", hashlib.sha256(payload).hexdigest())
    target = tmp_path / "x64" / "apply-seccomp"
    target.parent.mkdir()
    target.write_bytes(payload)
    target.chmod(0o644)
    assert seccomp.verify_apply_seccomp_sha256(str(target))
    assert seccomp.get_apply_seccomp_binary_path(str(target)) is None
    seccomp.reset_seccomp_path_cache()
    target.chmod(0o755)
    assert seccomp.get_apply_seccomp_binary_path(str(target)) == str(target)
