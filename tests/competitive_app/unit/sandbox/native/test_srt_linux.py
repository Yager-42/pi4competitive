"""O12 — SRT Linux bwrap argv / deny-scan / cleanup golden vectors.

Source parity: sandbox-runtime@0.0.67 linux-sandbox-utils / violation-monitor
tests (PORT, offline subset).
License: Apache-2.0 (retained under the native sandbox license directory)
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest

from competitive_app.adapter.out.sandbox.native.srt import linux as srt_linux
from competitive_app.adapter.out.sandbox.native.srt.linux import (
    build_sandbox_command,
    cleanup_bwrap_mount_points,
    find_first_nonexistent_component,
    find_symlink_in_path,
    generate_filesystem_args,
    has_file_ancestor,
    resolve_apply_seccomp_prefix,
    resolve_symlinked_deny_path,
    wrap_command_with_sandbox_linux,
)
from competitive_app.adapter.out.sandbox.native.srt.policy import (
    glob_to_regex,
    matches_domain_pattern,
)
from competitive_app.adapter.out.sandbox.native.srt.process import shell_quote
from competitive_app.adapter.out.sandbox.native.srt.seccomp import (
    get_apply_seccomp_binary_path,
)


def _no_seccomp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic wrap: disable seccomp prefix (vendored binary may or
    may not be present for this arch)."""
    monkeypatch.setattr(
        srt_linux, "resolve_apply_seccomp_prefix", lambda *a, **k: None
    )


def _setenv_pairs(argv: list[str]) -> dict[str, str]:
    return {
        argv[i + 1]: argv[i + 2]
        for i in range(len(argv) - 2)
        if argv[i] == "--setenv"
    }


def test_no_restrictions_returns_plain_shell_argv() -> None:
    argv = asyncio.run(
        wrap_command_with_sandbox_linux(
            command="true", needs_network_restriction=False
        )
    )
    assert argv == ["bash", "-c", "true"]


def test_weakening_switches_raise() -> None:
    with pytest.raises(ValueError, match="weakening"):
        asyncio.run(
            wrap_command_with_sandbox_linux(
                command="true",
                needs_network_restriction=False,
                allow_all_unix_sockets=True,
            )
        )
    with pytest.raises(ValueError, match="weakening"):
        asyncio.run(
            wrap_command_with_sandbox_linux(
                command="true",
                needs_network_restriction=False,
                enable_weaker_nested_sandbox=True,
            )
        )


def test_env_restrictions_become_unsetenv_setenv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(srt_linux, "ripgrep", _no_matches)
    _no_seccomp(monkeypatch)
    argv = asyncio.run(
        wrap_command_with_sandbox_linux(
            command="echo hi",
            needs_network_restriction=False,
            unset_env_vars=["SECRET"],
            set_env_vars={"FAKE": "sentinel"},
            write_config={"allowOnly": ["/dev/null"], "denyWithinAllow": []},
        )
    )
    assert argv[0] == "bwrap"
    assert "--unsetenv" in argv and "SECRET" in argv
    env = _setenv_pairs(argv)
    assert env.get("FAKE") == "sentinel"
    assert argv[-3:] == ["/bin/bash", "-c", "echo hi"]
    # write restriction => read-only root + /dev bind
    assert "--ro-bind" in argv
    assert "--dev" in argv


def test_network_restriction_uses_unshare_net_and_sockets(tmp_path) -> None:
    http_sock = tmp_path / "http.sock"
    socks_sock = tmp_path / "socks.sock"
    http_sock.write_bytes(b"")
    socks_sock.write_bytes(b"")
    argv = asyncio.run(
        wrap_command_with_sandbox_linux(
            command="echo hi",
            needs_network_restriction=True,
            http_socket_path=str(http_sock),
            socks_socket_path=str(socks_sock),
            http_proxy_port=41000,
            socks_proxy_port=41000,
            write_config=None,
            read_config=None,
        )
    )
    assert "--unshare-net" in argv
    assert "--bind" in argv and str(http_sock) in argv
    # proxy env lands via --setenv NAME VALUE pairs
    env = _setenv_pairs(argv)
    assert env.get("HTTP_PROXY") == "http://localhost:3128"
    assert env.get("HTTPS_PROXY") == "http://localhost:3128"
    assert env.get("CLAUDE_CODE_HOST_HTTP_PROXY_PORT") == "41000"
    assert env.get("CLAUDE_CODE_HOST_SOCKS_PROXY_PORT") == "41000"
    # PID namespace + userns + cap drop + fresh proc
    assert "--unshare-pid" in argv
    assert "--unshare-user" in argv
    assert "--cap-drop" in argv
    assert "--proc" in argv
    assert "--die-with-parent" in argv
    # inner script: socat listeners + trap + eval
    script = argv[-1]
    assert "TCP-LISTEN:3128" in script
    assert "TCP-LISTEN:1080" in script
    assert "trap \"kill %1 %2" in script


def test_network_blocked_without_sockets(monkeypatch) -> None:
    _no_seccomp(monkeypatch)
    argv = asyncio.run(
        wrap_command_with_sandbox_linux(
            command="true",
            needs_network_restriction=True,
            http_socket_path=None,
            socks_socket_path=None,
        )
    )
    assert "--unshare-net" in argv
    assert argv[-3:] == ["/bin/bash", "-c", "true"]


def test_missing_bridge_socket_raises(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="bridge socket does not exist"):
        asyncio.run(
            wrap_command_with_sandbox_linux(
                command="true",
                needs_network_restriction=True,
                http_socket_path=str(tmp_path / "missing.sock"),
                socks_socket_path=str(tmp_path / "missing2.sock"),
            )
        )


async def _no_matches(*_args, **_kwargs) -> list[str]:
    return []


def test_mandatory_deny_paths_from_ripgrep(tmp_path, monkeypatch) -> None:
    cwd = tmp_path / "ws"
    cwd.mkdir()
    (cwd / ".git").mkdir()
    monkeypatch.setattr(
        srt_linux,
        "ripgrep",
        lambda *a, **k: _async_fixture(
            [
                ".bashrc",
                ".mcp.json",
                ".git/hooks/pre-commit",
                ".git/config",
                "sub/.env",
            ]
        ),
    )
    deny = asyncio.run(
        srt_linux.linux_get_mandatory_deny_paths(str(cwd))
    )
    # dangerous files at root, git hooks/config, nested .env file
    assert str(cwd / ".bashrc") in deny
    assert str(cwd / ".mcp.json") in deny
    assert str(cwd / ".git" / "hooks") in deny
    assert str(cwd / ".git" / "config") in deny
    assert str(cwd / "sub" / ".env") in deny
    # dedup keeps one entry per path
    assert len(deny) == len(set(deny))


async def _async_fixture(lines: list[str]) -> list[str]:
    return lines


def test_allow_git_config_skips_git_config_deny(tmp_path, monkeypatch) -> None:
    cwd = tmp_path / "ws"
    cwd.mkdir()
    (cwd / ".git").mkdir()
    monkeypatch.setattr(
        srt_linux,
        "ripgrep",
        lambda *a, **k: _async_fixture([".git/hooks/pre-commit"]),
    )
    deny = asyncio.run(
        srt_linux.linux_get_mandatory_deny_paths(str(cwd), allow_git_config=True)
    )
    assert str(cwd / ".git" / "hooks") in deny
    assert str(cwd / ".git" / "config") not in deny


def test_build_sandbox_command_golden() -> None:
    cmd = build_sandbox_command(
        "/tmp/http.sock",
        "/tmp/socks.sock",
        "echo hi",
        apply_seccomp_prefix=None,
        shell="/bin/bash",
        socat_path="/usr/bin/socat",
    )
    assert cmd.startswith("/bin/bash -c ")
    # the whole inner script is shell-quoted once more, so the eval line's
    # quotes appear escaped in the outer string
    expected_inner = "\n".join(
        [
            "/usr/bin/socat TCP-LISTEN:3128,fork,reuseaddr UNIX-CONNECT:/tmp/http.sock >/dev/null 2>&1 &",
            "/usr/bin/socat TCP-LISTEN:1080,fork,reuseaddr UNIX-CONNECT:/tmp/socks.sock >/dev/null 2>&1 &",
            'trap "kill %1 %2 2>/dev/null; exit" EXIT',
            "eval 'echo hi'",
        ]
    )
    assert cmd == "/bin/bash -c " + shell_quote([expected_inner])

    cmd2 = build_sandbox_command(
        "/tmp/http.sock",
        "/tmp/socks.sock",
        "echo hi",
        apply_seccomp_prefix="'/opt/apply-seccomp' ",
        shell="/bin/bash",
    )
    expected_inner2 = "\n".join(
        [
            "socat TCP-LISTEN:3128,fork,reuseaddr UNIX-CONNECT:/tmp/http.sock >/dev/null 2>&1 &",
            "socat TCP-LISTEN:1080,fork,reuseaddr UNIX-CONNECT:/tmp/socks.sock >/dev/null 2>&1 &",
            'trap "kill %1 %2 2>/dev/null; exit" EXIT',
            "'/opt/apply-seccomp' /bin/bash -c 'echo hi'",
        ]
    )
    assert cmd2 == "/bin/bash -c " + shell_quote([expected_inner2])


def test_resolve_apply_seccomp_prefix_uses_vendored_binary() -> None:
    binary = get_apply_seccomp_binary_path()
    prefix = resolve_apply_seccomp_prefix(None, None)
    if binary is not None:
        assert prefix == f"{binary} "
    else:
        assert prefix is None


def test_resolve_apply_seccomp_prefix_argv0_mode() -> None:
    prefix = resolve_apply_seccomp_prefix("/opt/srt/bin", "srt-seccomp")
    assert prefix == "ARGV0=srt-seccomp /opt/srt/bin "
    with pytest.raises(ValueError, match="requires"):
        resolve_apply_seccomp_prefix(None, "srt-seccomp")


def test_filesystem_args_non_existent_deny_within_allow(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    args = asyncio.run(
        generate_filesystem_args(
            None,
            {"allowOnly": [str(ws)], "denyWithinAllow": [str(ws / ".env")]},
            cwd=str(ws),
        )
    )
    # /dev/null ro-bind at the first non-existent component (the .env leaf)
    assert "--ro-bind" in args
    assert "/dev/null" in args
    assert str(ws / ".env") in args


def test_filesystem_args_deny_read_tmpfs_with_allow_back(tmp_path) -> None:
    denied_dir = tmp_path / "denied"
    denied_dir.mkdir()
    allow_file = denied_dir / "ok.txt"
    allow_file.write_text("x")
    args = asyncio.run(
        generate_filesystem_args(
            {"denyOnly": [str(denied_dir)], "allowWithinDeny": [str(allow_file)]},
            None,
            cwd=str(tmp_path),
        )
    )
    # one of the --tmpfs mounts covers the denied dir; the allowed file is
    # re-bound read-only afterwards
    tmpfs_targets = {
        args[i + 1] for i in range(len(args) - 1) if args[i] == "--tmpfs"
    }
    assert str(denied_dir) in tmpfs_targets
    assert "--ro-bind" in args
    ro_pairs = {
        args[i + 2] for i in range(len(args) - 2) if args[i] == "--ro-bind"
    }
    assert str(allow_file) in ro_pairs


def test_symlink_helpers(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    target = ws / "real"
    target.mkdir()
    link = ws / "link"
    link.symlink_to(target, target_is_directory=True)
    assert find_symlink_in_path(str(link / "x"), [str(ws)]) == str(link)
    assert find_symlink_in_path(str(ws / "x" / "y"), [str(ws)]) is None
    assert has_file_ancestor(str(ws / "real" / "a" / "b")) is False
    assert has_file_ancestor(str(target / "f" / "x")) is False
    assert find_first_nonexistent_component(str(ws / "a" / "b" / "c")) == str(ws / "a")
    assert resolve_symlinked_deny_path(str(link / "x")) == str(target / "x")


def test_cleanup_bwrap_mount_points(tmp_path) -> None:
    empty_file = tmp_path / "mount"
    empty_file.write_bytes(b"")
    srt_linux._BWRAP_MOUNT_POINTS.add(str(empty_file))
    cleanup_bwrap_mount_points(force=True)
    assert not empty_file.exists()
    assert srt_linux._BWRAP_MOUNT_POINTS == set()

    nonempty = tmp_path / "keep"
    nonempty.write_text("real content")
    srt_linux._BWRAP_MOUNT_POINTS.add(str(nonempty))
    cleanup_bwrap_mount_points(force=True)
    assert nonempty.exists()


def test_glob_to_regex_golden() -> None:
    assert glob_to_regex("*.ts") == r"^[^/]*\.ts$"
    assert glob_to_regex("src/**/*.ts") == r"^src/(.*/)?[^/]*\.ts$"
    assert glob_to_regex("**/.env") == r"^(.*/)?\.env$"
    assert glob_to_regex("file?.txt") == r"^file[^/]\.txt$"
    assert glob_to_regex("file[0-9].txt") == r"^file[0-9]\.txt$"
    assert glob_to_regex("unclosed[") == r"^unclosed\[$"
    assert glob_to_regex("/Users/*/Library/**") == r"^/Users/[^/]*/Library/.*$"


def test_domain_pattern_matching() -> None:
    assert matches_domain_pattern("example.com", "example.com")
    assert matches_domain_pattern("EXAMPLE.COM", "example.com")
    assert matches_domain_pattern("sub.example.com", "*.example.com")
    assert not matches_domain_pattern("example.com", "*.example.com")
    assert matches_domain_pattern("anything", "*")
    assert not matches_domain_pattern("1.2.3.4", "*.3.4")
    assert matches_domain_pattern("::1", "*")


# ---------------------------------------------------------------------------
# Linux violation monitor (linux-violation-monitor.ts)
# ---------------------------------------------------------------------------

def test_violation_monitor_filters_and_forwards(tmp_path, monkeypatch) -> None:
    events: list = []
    monitor = srt_linux.start_linux_sandbox_violation_monitor(
        events.append,
        {
            "allowWritePaths": [str(tmp_path)],
            "denyWritePaths": [str(tmp_path / "secret")],
            "ignoreViolations": {"*": ["/tmp/noisy"]},
        },
    )

    async def _run() -> None:
        await monitor.start()
        assert monitor.observe_socket_path is not None
        reader, writer = await asyncio.open_unix_connection(
            monitor.observe_socket_path
        )
        # header line carries the encoded command
        writer.write(
            json.dumps(
                {"encodedCommand": "Y21k"}  # b64("cmd")
            ).encode()
            + b"\n"
        )
        await writer.drain()
        # allowed write inside allow path → no violation
        writer.write(
            json.dumps({"syscall": "openat", "path": str(tmp_path / "ok.txt")}).encode()
            + b"\n"
        )
        await writer.drain()
        # outside allow path → violation
        writer.write(
            json.dumps({"syscall": "openat", "path": "/etc/passwd"}).encode()
            + b"\n"
        )
        await writer.drain()
        # inside denyWrite carve-out → violation
        writer.write(
            json.dumps({"syscall": "openat", "path": str(tmp_path / "secret" / "x")}).encode()
            + b"\n"
        )
        await writer.drain()
        # ignored path → no violation
        writer.write(
            json.dumps({"syscall": "openat", "path": "/tmp/noisy/thing"}).encode()
            + b"\n"
        )
        await writer.drain()
        await asyncio.sleep(0.2)
        writer.close()
        monitor.stop()

    asyncio.run(_run())
    lines = [e.line for e in events]
    assert len(lines) == 2, lines
    assert lines[0] == "deny openat /etc/passwd"
    assert lines[1] == "deny openat " + str(tmp_path / "secret" / "x")
    assert events[0].command == "cmd"
