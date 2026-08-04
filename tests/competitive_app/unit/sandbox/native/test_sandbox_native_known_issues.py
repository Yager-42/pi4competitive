from __future__ import annotations

import asyncio
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
from competitive_app.adapter.out.sandbox.native.workspace import ensure_workspace
from competitive_app.adapter.out.sandbox.exceptions import SandboxPermissionError


SCOPE = "a" * 64


def test_config_non_string_key_is_value_error() -> None:
    with pytest.raises(ValueError, match="unknown root key: 1"):
        parse_pi_sandbox_config({1: {}})

def test_linux_default_secret_globs_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from competitive_app.adapter.out.sandbox.native import policy
    from competitive_app.adapter.out.sandbox.native.srt import manager

    monkeypatch.setattr(policy.sys, "platform", "linux")
    default = policy.create_default_policy("/workspace/project")
    deny_write = default["filesystem"]["denyWrite"]
    for pattern in ("**/.env.*", "**/*.pem", "**/*.key", "**/*.p12", "**/*.pfx"):
        assert pattern in deny_write
    monkeypatch.setattr(manager, "get_platform", lambda: "linux")
    monkeypatch.setattr(manager, "_config", default)
    with pytest.raises(ValueError, match="cannot be enforced"):
        manager._get_fs_write_config()


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


def test_manifest_staging_rejects_symlink_destination(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("original")
    (workspace / "approved_tools.json").symlink_to(outside)
    source = tmp_path / "manifest.json"
    source.write_text("trusted")
    with pytest.raises(SandboxPermissionError):
        _stage_manifest(source, workspace)
    assert outside.read_text() == "original"


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

        def is_closing(self) -> bool:
            return False

        def write(self, value: bytes) -> None:
            self.lines.append(value)

        async def drain(self) -> None:
            return None

    writer = Writer()
    pending: dict[str, asyncio.Future] = {}
    task = asyncio.create_task(broker._ask_network("api.example.com", 443, writer, pending))
    while not writer.lines:
        await asyncio.sleep(0)
    request_id = next(iter(pending))
    pending[request_id].set_result(True)
    assert await task is True
    assert calls == 2
