"""O13 — SRT macOS Seatbelt profile / argv golden vectors.

Source parity: sandbox-runtime@0.0.67 macOS seatbelt tests (PORT, offline).
License: Apache-2.0 (retained under the native sandbox license directory)
"""
from __future__ import annotations

import base64
import os

import pytest

from competitive_app.adapter.out.sandbox.native.srt.macos import (
    escape_path,
    generate_log_tag,
    generate_read_rules,
    generate_sandbox_profile,
    generate_write_rules,
    mac_get_mandatory_deny_patterns,
    wrap_command_with_sandbox_macos,
)
from competitive_app.adapter.out.sandbox.native.srt.policy import glob_to_regex
from competitive_app.adapter.out.sandbox.native.srt.process import shell_quote


def test_profile_header_and_default_deny() -> None:
    profile = generate_sandbox_profile(
        read_config=None, write_config=None, needs_network_restriction=True, log_tag="TAG"
    )
    assert profile.startswith("(version 1)\n(deny default (with message \"TAG\"))\n")
    assert "; LogTag: TAG" in profile
    assert "(allow process-exec)" in profile
    assert "(allow process-fork)" in profile


def test_profile_no_network_restriction_allows_network() -> None:
    profile = generate_sandbox_profile(
        read_config=None, write_config=None, needs_network_restriction=False, log_tag="T"
    )
    assert "(allow network*)" in profile


def test_profile_network_restriction_blocks_and_proxy_allows() -> None:
    profile = generate_sandbox_profile(
        read_config=None,
        write_config=None,
        needs_network_restriction=True,
        http_proxy_port=41000,
        socks_proxy_port=41001,
        log_tag="T",
    )
    assert "(allow network*)" not in profile
    assert '(allow network-bind (local ip "localhost:41000"))' in profile
    assert '(allow network-outbound (remote ip "localhost:41001"))' in profile


def test_profile_unix_socket_rules() -> None:
    profile = generate_sandbox_profile(
        read_config=None,
        write_config=None,
        needs_network_restriction=True,
        allow_unix_sockets=["/var/run/docker.sock"],
        log_tag="T",
    )
    assert "(allow system-socket (socket-domain AF_UNIX))" in profile
    assert (
        '(allow network-bind (local unix-socket (subpath "/var/run/docker.sock")))'
        in profile
    )


def test_profile_allow_local_binding() -> None:
    profile = generate_sandbox_profile(
        read_config=None,
        write_config=None,
        needs_network_restriction=True,
        allow_local_binding=True,
        http_proxy_port=41000,
        log_tag="T",
    )
    assert '(allow network-bind (local ip "*:*"))' in profile
    assert '(allow network-outbound (remote ip "localhost:*"))' in profile


def test_profile_mach_lookup_and_apple_events() -> None:
    profile = generate_sandbox_profile(
        read_config=None,
        write_config=None,
        needs_network_restriction=False,
        allow_mach_lookup=["com.example.*", "com.other.Service"],
        allow_apple_events=True,
        log_tag="T",
    )
    assert '(allow mach-lookup (global-name-prefix "com.example."))' in profile
    assert '(allow mach-lookup (global-name "com.other.Service"))' in profile
    assert "(allow appleevent-send)" in profile
    assert "(allow lsopen)" in profile


def test_read_rules_deny_then_allow_back() -> None:
    rules = generate_read_rules(
        {
            "denyOnly": ["/Users/me/private"],
            "allowWithinDeny": ["/Users/me/private/work"],
        },
        "T",
    )
    text = "\n".join(rules)
    assert "(allow file-read*)" in rules[0]
    assert '(deny file-read*\n  (subpath "/Users/me/private")' in text
    assert '(allow file-read*\n  (subpath "/Users/me/private/work")' in text
    # metadata stat allowed for traversal
    assert "(allow file-read-metadata\n  (vnode-type DIRECTORY))" in text
    # move blocking protects the denied region
    assert '(deny file-write-unlink\n  (subpath "/Users/me/private")' in text


def test_read_rules_root_deny_reallows_literal_root() -> None:
    rules = generate_read_rules({"denyOnly": ["/"]}, "T")
    assert '(allow file-read* (literal "/"))' in "\n".join(rules)


def test_write_rules_allow_and_deny_globs() -> None:
    rules = generate_write_rules(
        {"allowOnly": ["/Users/me/work"], "denyWithinAllow": ["**/.env"]},
        "T",
    )
    text = "\n".join(rules)
    assert '(allow file-write*\n  (subpath "/Users/me/work")' in text
    # relative globs are cwd-joined before regex conversion (upstream
    # normalizePathForSandbox behavior); the regex is JSON-escaped
    # (upstream escapePath = JSON.stringify doubles backslashes)
    cwd_env = escape_path(glob_to_regex(os.path.join(os.getcwd(), "**", ".env")))
    assert f"(regex {cwd_env})" in text
    assert "(deny file-write*" in text


def test_write_rules_none_allow_all() -> None:
    assert generate_write_rules(None, "T") == ["(allow file-write*)"]


def test_pty_rules() -> None:
    profile = generate_sandbox_profile(
        read_config=None,
        write_config=None,
        needs_network_restriction=False,
        allow_pty=True,
        log_tag="T",
    )
    assert "(allow pseudo-tty)" in profile
    assert '(allow file-ioctl\n  (literal "/dev/ptmx")' in profile


def test_mandatory_deny_patterns() -> None:
    patterns = mac_get_mandatory_deny_patterns()
    assert "**/.git/hooks/**" in patterns
    assert "**/.git/config" in patterns
    assert "**/.bashrc" in patterns
    assert "**/.claude/commands/**" in patterns
    patterns_no_git_config = mac_get_mandatory_deny_patterns(allow_git_config=True)
    assert "**/.git/config" not in patterns_no_git_config
    assert "**/.git/hooks/**" in patterns_no_git_config


def test_log_tag_encoding() -> None:
    tag = generate_log_tag("echo hi")
    payload = tag[len("CMD64_") : tag.index("_END")]
    assert base64.b64decode(payload).decode() == "echo hi"
    assert tag.endswith("_SBX")


def test_wrap_no_restrictions_passthrough() -> None:
    argv = wrap_command_with_sandbox_macos(
        command="true",
        needs_network_restriction=False,
    )
    assert argv == ["bash", "-c", "true"]


def test_wrap_argv_shape() -> None:
    argv = wrap_command_with_sandbox_macos(
        command="echo hi",
        needs_network_restriction=False,
        read_config={"denyOnly": ["/etc/passwd"]},
        write_config={"allowOnly": ["/tmp/x"], "denyWithinAllow": []},
        bin_shell="/bin/zsh",
    )
    assert argv[0] == "env"
    assert "/usr/bin/sandbox-exec" in argv
    assert "-p" in argv
    profile = argv[argv.index("-p") + 1]
    assert profile.startswith("(version 1)")
    assert '(deny file-read*\n  (subpath "/etc/passwd")' in profile
    assert argv[-3:] == ["/bin/zsh", "-c", "echo hi"]


def test_wrap_env_drop_and_set() -> None:
    argv = wrap_command_with_sandbox_macos(
        command="env",
        needs_network_restriction=False,
        unset_env_vars=["SECRET"],
        set_env_vars={"FAKE": "sentinel"},
        write_config={"allowOnly": ["/tmp/x"], "denyWithinAllow": []},
    )
    assert "-u" in argv
    assert argv[argv.index("-u") + 1] == "SECRET"
    assert "FAKE=sentinel" in argv


def test_wrap_masked_file_binds_degrade_to_read_deny() -> None:
    argv = wrap_command_with_sandbox_macos(
        command="true",
        needs_network_restriction=False,
        masked_file_binds=[{"realPath": "/Users/me/.netrc", "fakePath": "/tmp/fake"}],
        write_config={"allowOnly": ["/tmp/x"], "denyWithinAllow": []},
    )
    profile = argv[argv.index("-p") + 1]
    assert '(deny file-read*\n  (subpath "/Users/me/.netrc")' in profile
    assert "/tmp/fake" not in profile


def test_glob_to_regex_matches_seatbelt_usage() -> None:
    assert glob_to_regex("**/.env") == r"^(.*/)?\.env$"
    assert glob_to_regex("/Users/*/Library/**") == r"^/Users/[^/]*/Library/.*$"


def test_shell_quote_golden() -> None:
    assert shell_quote(["echo", "hello"]) == "echo hello"
    assert shell_quote(["a b"]) == "'a b'"
    assert shell_quote(["it's"]) == "'it'\"'\"'s'"
    assert shell_quote(["=ls"]) == "'=ls'"
    assert shell_quote([""]) == "''"
