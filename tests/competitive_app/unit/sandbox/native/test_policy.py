"""O2–O3 — default sandbox policy + workspace secret denials (PORT of
policy.test.ts).

Source: pi-sandbox@0.4.2 ``policy.test.ts``
License: Apache-2.0 (retained under the native sandbox license directory)
"""
from __future__ import annotations

import os
from pathlib import Path

from competitive_app.adapter.out.sandbox.native.policy import (
    create_default_policy,
    create_workspace_secret_deny_write_paths,
    is_secret_deny_write_basename,
    to_sandbox_runtime_config,
)


def test_default_policy_limits_writes_and_protects_config() -> None:
    policy = create_default_policy("/workspace/project")
    assert policy["filesystem"]["allowWrite"] == ["/workspace/project", "/dev/null"]
    deny_write = policy["filesystem"]["denyWrite"]
    assert "/workspace/project/.pi/sandbox.json" in deny_write
    assert "/workspace/project/.pi/pi-auto-review.json" in deny_write
    home = str(Path.home())
    for protected in [
        os.path.join(home, ".pi", "agent", "settings.json"),
        os.path.join(home, ".pi", "agent", "permissions.json"),
        os.path.join(home, ".pi", "agent", "pi-sandbox.json"),
        os.path.join(home, ".pi", "agent", "logs"),
        os.path.join(home, ".pi", "agent", "extensions"),
        os.path.join(home, ".pi", "agent", "extensions", "pi-sandbox", "config.json"),
    ]:
        assert protected in deny_write, protected
    assert policy["network"]["allowedDomains"] == []
    assert policy["network"]["deniedDomains"] == []
    assert policy["network"]["allowLocalBinding"] is False
    assert policy["network"]["allowAllUnixSockets"] is False

    runtime = to_sandbox_runtime_config(policy)
    assert runtime["filesystem"]["allowGitConfig"] is True
    assert runtime["network"]["allowedDomains"] == []
    assert runtime["filesystem"]["allowWrite"] == ["/workspace/project", "/dev/null"]


def test_default_policy_denies_writes_to_common_workspace_secrets() -> None:
    workspace = "/workspace/project"
    policy = create_default_policy(workspace)
    deny_write = policy["filesystem"]["denyWrite"]
    assert os.path.join(workspace, ".env") in deny_write
    assert os.path.join(workspace, ".env.local") in deny_write
    assert os.path.join(workspace, ".env.production") in deny_write
    assert os.path.join(workspace, "secrets") in deny_write
    assert os.path.join(workspace, ".secrets") in deny_write
    assert os.path.join(workspace, ".env.example") not in deny_write


def test_secret_basename_classification() -> None:
    assert is_secret_deny_write_basename(".env") is True
    assert is_secret_deny_write_basename(".env.preview") is True
    assert is_secret_deny_write_basename("server.pem") is True
    assert is_secret_deny_write_basename("tls.KEY") is True
    assert is_secret_deny_write_basename(".env.example") is False
    assert is_secret_deny_write_basename(".env.sample") is False
    assert is_secret_deny_write_basename("README.md") is False


def test_workspace_secret_deny_paths_discover_nested_secrets(tmp_path) -> None:
    root = tmp_path
    nested = root / "apps" / "api"
    nested.mkdir(parents=True)
    (nested / ".env").write_text("SECRET=1\n")
    (nested / "server.pem").write_text("cert\n")
    (nested / ".env.example").write_text("SECRET=\n")
    (root / "packages" / "web" / "secrets").mkdir(parents=True)

    deny_write = create_workspace_secret_deny_write_paths(str(root), "linux")
    assert str(root / ".env") in deny_write
    assert str(nested / ".env") in deny_write
    assert str(nested / "server.pem") in deny_write
    assert str(root / "packages" / "web" / "secrets") in deny_write
    assert str(nested / ".env.example") not in deny_write
    assert not any("*" in path for path in deny_write)


def test_darwin_secret_deny_paths_include_nested_create_globs() -> None:
    deny_write = create_workspace_secret_deny_write_paths(
        "/workspace/project", "darwin"
    )
    assert "**/.env" in deny_write
    assert "**/*.pem" in deny_write
    assert "**/secrets/**" in deny_write
    assert "/workspace/project/.env" in deny_write


def test_additional_read_paths_extend_default_allowlist() -> None:
    policy = create_default_policy(
        "/workspace/project",
        ["/home/user/.local/bin/rtk", "/opt/tools/helper"],
    )
    allow_read = policy["filesystem"]["allowRead"]
    assert "/workspace/project" in allow_read
    assert "/dev/null" in allow_read
    assert "/home/user/.local/bin/rtk" in allow_read
    assert "/opt/tools/helper" in allow_read


def test_default_policy_home_read_deny() -> None:
    home = str(Path.home())
    policy = create_default_policy("/workspace/project")
    assert policy["filesystem"]["denyRead"] == [home]


def test_interpretter_and_package_roots_are_readable() -> None:
    policy = create_default_policy("/workspace/project")
    allow_read = policy["filesystem"]["allowRead"]
    from competitive_app.adapter.out.sandbox.native.policy import (
        INTERPRETER_ROOT,
        SANDBOX_RUNTIME_ROOT,
    )

    assert str(INTERPRETER_ROOT) in allow_read
    assert str(SANDBOX_RUNTIME_ROOT) in allow_read
