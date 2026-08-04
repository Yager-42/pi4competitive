from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from competitive_app.adapter.out.sandbox.native import broker
from competitive_app.adapter.out.sandbox.native.config import parse_pi_sandbox_config
from competitive_app.adapter.out.sandbox.native.native_sandbox_provider import (
    NativeSandboxProvider,
    _stage_manifest,
)
from competitive_app.adapter.out.sandbox.native.policy import (
    _collect_nested_secret_deny_write_paths,
)
from competitive_app.adapter.out.sandbox.native.workspace import (
    ensure_workspace,
    open_workspace_descriptor,
)
from competitive_app.adapter.out.sandbox.exceptions import SandboxPermissionError


SCOPE = "a" * 64


def test_config_non_string_key_is_value_error() -> None:
    with pytest.raises(ValueError, match="unknown root key: 1"):
        parse_pi_sandbox_config({1: {}})

def test_linux_default_secret_globs_are_not_emitted(monkeypatch: pytest.MonkeyPatch) -> None:
    from competitive_app.adapter.out.sandbox.native import policy
    from competitive_app.adapter.out.sandbox.native.srt import manager

    monkeypatch.setattr(policy.sys, "platform", "linux")
    default = policy.create_default_policy("/workspace/project")
    deny_write = default["filesystem"]["denyWrite"]
    assert not any("*" in path for path in deny_write)
    monkeypatch.setattr(manager, "get_platform", lambda: "linux")
    monkeypatch.setattr(manager, "_config", default)
    assert manager._get_fs_write_config()["denyWithinAllow"]


def test_linux_write_globs_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from competitive_app.adapter.out.sandbox.native.srt import manager

    monkeypatch.setattr(manager, "get_platform", lambda: "linux")
    monkeypatch.setattr(
        manager,
        "_config",
        {"filesystem": {"allowWrite": [], "denyWrite": ["**/*.pem"]}},
    )
    with pytest.raises(ValueError, match="cannot be enforced"):
        manager._get_fs_write_config()


def test_common_new_root_secrets_are_concrete_linux_denials() -> None:
    from competitive_app.adapter.out.sandbox.native.policy import create_default_policy

    deny_write = create_default_policy("/workspace/project")["filesystem"]["denyWrite"]
    assert "/workspace/project/.env.preview" in deny_write
    assert "/workspace/project/server.key" in deny_write
    assert "/workspace/project/cert.pem" in deny_write


def test_secret_scan_does_not_follow_symlink_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / ".env").write_text("secret")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "linked").symlink_to(outside, target_is_directory=True)
    assert _collect_nested_secret_deny_write_paths(str(workspace)) == []


def test_workspace_rejects_symlink_scope_atomically(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / SCOPE).symlink_to(outside, target_is_directory=True)
    with pytest.raises(SandboxPermissionError):
        ensure_workspace(root, SCOPE)


def test_manifest_staging_replaces_symlink_without_touching_target(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("original")
    (workspace / "approved_tools.json").symlink_to(outside)
    source = tmp_path / "manifest.json"
    source.write_text("trusted")
    staged = _stage_manifest(source, workspace)
    assert staged.read_text() == "trusted"
    assert outside.read_text() == "original"


def test_manifest_staging_hardlink_cannot_truncate_external_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("original")
    (workspace / "approved_tools.json").hardlink_to(outside)
    source = tmp_path / "manifest.json"
    source.write_text("trusted")
    _stage_manifest(source, workspace)
    assert outside.read_text() == "original"
    assert (workspace / "approved_tools.json").read_text() == "trusted"


def test_descriptor_relative_manifest_staging_survives_scope_rename(tmp_path: Path) -> None:
    root = tmp_path / "root"
    workspace, workspace_fd = open_workspace_descriptor(root, SCOPE)
    source = tmp_path / "manifest.json"
    source.write_text("trusted")
    moved = tmp_path / "moved"
    workspace.rename(moved)
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace.symlink_to(outside, target_is_directory=True)
    try:
        _stage_manifest(source, workspace, directory_fd=workspace_fd)
        fd = os.open("approved_tools.json", os.O_RDONLY, dir_fd=workspace_fd)
        try:
            assert os.read(fd, 100) == b"trusted"
        finally:
            os.close(fd)
        assert not (outside / "approved_tools.json").exists()
    finally:
        os.close(workspace_fd)


@pytest.mark.asyncio
async def test_release_signals_running_scope_before_runtime_close(tmp_path: Path) -> None:
    events: list[str] = []

    class Runtime:
        async def close(self) -> None:
            events.append("close")

    class Factory:
        def __call__(self, *args, **kwargs):
            return Runtime()

    provider = NativeSandboxProvider(sandbox_root=tmp_path, runtime_factory=Factory())
    await provider.acquire(SCOPE)
    signal = provider._signals[SCOPE]
    original = provider._active[SCOPE]._runtime.close

    async def close() -> None:
        events.append(f"signal={signal.done()}")
        await original()

    provider._active[SCOPE]._runtime.close = close
    await provider.release(SCOPE)
    assert events == ["signal=True", "close"]


@pytest.mark.asyncio
async def test_provider_retains_workspace_descriptor_until_release(tmp_path: Path) -> None:
    provider = NativeSandboxProvider(sandbox_root=tmp_path)
    await provider.acquire(SCOPE)
    workspace_fd = provider._workspace_fds[SCOPE]
    os.fstat(workspace_fd)
    await provider.release(SCOPE)
    with pytest.raises(OSError):
        os.fstat(workspace_fd)


@pytest.mark.asyncio
async def test_broker_rechecks_hostname_after_parent_approval(monkeypatch) -> None:
    calls = 0

    async def validate(value: str) -> str | None:
        nonlocal calls
        calls += 1
        return value

    monkeypatch.setattr(broker, "validate_public_hostname", validate)

    class Writer:
        def __init__(self) -> None:
            self.lines: list[bytes] = []
            self.drains = 0

        def is_closing(self) -> bool:
            return False

        def write(self, value: bytes) -> None:
            self.lines.append(value)

        async def drain(self) -> None:
            self.drains += 1

    writer = Writer()
    pending: dict[str, asyncio.Future] = {}
    task = asyncio.create_task(broker._ask_network("api.example.com", 443, writer, pending))

    async def wait_for_request() -> None:
        while not writer.lines:
            await asyncio.sleep(0)

    try:
        await asyncio.wait_for(wait_for_request(), timeout=1)
    except BaseException:
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        raise
    request_id = next(iter(pending))
    pending[request_id].set_result(True)
    assert await task is True
    assert writer.drains == 1
    # Approval must re-validate the hostname before the proxy dials.
    assert calls == 2


@pytest.mark.asyncio
async def test_ripgrep_cancellation_kills_and_awaits_process(monkeypatch: pytest.MonkeyPatch) -> None:
    from competitive_app.adapter.out.sandbox.native.srt import process

    started = asyncio.Event()
    cancelled = asyncio.Event()

    class FakeProcess:
        returncode: int | None = None
        waited = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        async def wait(self) -> int:
            self.waited += 1
            if self.returncode is None:
                self.returncode = 0
            return self.returncode or 0

        def kill(self) -> None:
            self.returncode = -9

    fake = FakeProcess()

    async def spawn(*args, **kwargs):
        return fake
    monkeypatch.setattr(process.asyncio, "create_subprocess_exec", spawn)
    abort_signal = asyncio.get_running_loop().create_future()
    task = asyncio.create_task(process.ripgrep([], "/tmp", abort_signal))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fake.returncode == -9
    assert cancelled.is_set()
    assert fake.waited == 1  # killed children must be reaped, not left zombies


@pytest.mark.asyncio
async def test_negative_content_length_is_rejected_before_forwarding() -> None:
    from competitive_app.adapter.out.sandbox.native.srt import proxy

    reader = asyncio.StreamReader()
    reader.feed_data(b"attacker-bytes")
    reader.feed_eof()
    with pytest.raises(ValueError, match="negative Content-Length"):
        await proxy._read_body(reader, {"content-length": "-1"})
    assert not reader.at_eof()
