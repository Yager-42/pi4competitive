"""SRT macOS sandbox — Seatbelt profile generation, sandbox-exec argv,
mandatory deny glob patterns, and the unified log violation monitor.

Source: sandbox-runtime@0.0.67 ``src/sandbox/macos-sandbox-utils.ts``
Repository: anthropics/sandbox-runtime @ 21d8f75e1bc00eede09b3103e68b2eae097110d1
License: Apache-2.0 (retained under the native sandbox license directory)

Host delta (ADAPT, per G0 map §4.1): ``wrapCommandWithSandboxMacOS`` returns
an argv list (``env ... sandbox-exec -p profile shell -c command``) for a
direct spawn instead of a shell-quoted string. Credential whole-file masks
degrade to read-deny exactly like upstream (SBPL cannot redirect reads);
the DYLD interposer note is retained. The log monitor is asyncio-spawned
(macOS real gate only). ``SandboxViolationEvent`` is a dataclass with the
upstream field names (``timestamp`` is optional in Python).
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import os
import random
import re
import string
from dataclasses import dataclass
from typing import Callable

from .policy import (
    DANGEROUS_FILES,
    FsReadRestrictionConfig,
    FsWriteRestrictionConfig,
    build_posix_git_safe_dir_env,
    contains_glob_chars,
    decode_sandboxed_command,
    encode_sandboxed_command,
    generate_proxy_env_vars,
    get_dangerous_directories,
    glob_to_regex,
    normalize_path_for_sandbox,
)
from .process import log_for_debugging, which


@dataclass
class SandboxViolationEvent:
    line: str
    command: str | None = None
    encodedCommand: str | None = None
    timestamp: _dt.datetime | None = None


SandboxViolationCallback = Callable[[SandboxViolationEvent], None]


def _random_suffix() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=9))


_session_suffix = "_" + _random_suffix() + "_SBX"


def mac_get_mandatory_deny_patterns(allow_git_config: bool = False) -> list[str]:
    """Mandatory deny patterns as glob patterns (no filesystem scanning)."""
    cwd = os.getcwd()
    deny_paths: list[str] = []

    for file_name in DANGEROUS_FILES:
        deny_paths.append(os.path.join(cwd, file_name))
        deny_paths.append(f"**/{file_name}")

    for dir_name in get_dangerous_directories():
        deny_paths.append(os.path.join(cwd, dir_name))
        deny_paths.append(f"**/{dir_name}/**")

    deny_paths.append(os.path.join(cwd, ".git/hooks"))
    deny_paths.append("**/.git/hooks/**")

    if not allow_git_config:
        deny_paths.append(os.path.join(cwd, ".git/config"))
        deny_paths.append("**/.git/config")

    return list(dict.fromkeys(deny_paths))


def generate_log_tag(command: str) -> str:
    encoded_command = encode_sandboxed_command(command)
    return f"CMD64_{encoded_command}_END{_session_suffix}"


def get_ancestor_directories(path_str: str) -> list[str]:
    """All ancestor directories up to (not including) root."""
    ancestors: list[str] = []
    current_path = os.path.dirname(path_str)
    while current_path not in ("/", "."):
        ancestors.append(current_path)
        parent_path = os.path.dirname(current_path)
        if parent_path == current_path:
            break
        current_path = parent_path
    return ancestors


def escape_path(path_str: str) -> str:
    """Seatbelt literal escaping — JSON.stringify parity."""
    return json.dumps(path_str, ensure_ascii=False)


def generate_move_blocking_rules(
    path_patterns: list[str], log_tag: str
) -> list[str]:
    """Deny file-write-unlink/create on protected paths + their ancestors."""
    rules: list[str] = []
    ops = ("file-write-unlink", "file-write-create")

    for path_pattern in path_patterns:
        normalized_path = normalize_path_for_sandbox(path_pattern)

        if contains_glob_chars(normalized_path):
            regex_pattern = glob_to_regex(normalized_path)
            for op in ops:
                rules.append(f"(deny {op}")
                rules.append(f"  (regex {escape_path(regex_pattern)})")
                rules.append(f'  (with message "{log_tag}"))')

            static_prefix = re.split(r"[*?\[\]]", normalized_path)[0]
            if static_prefix and static_prefix != "/":
                base_dir = (
                    static_prefix[:-1]
                    if static_prefix.endswith("/")
                    else os.path.dirname(static_prefix)
                )
                for op in ops:
                    rules.append(f"(deny {op}")
                    rules.append(f"  (literal {escape_path(base_dir)})")
                    rules.append(f'  (with message "{log_tag}"))')
                for ancestor_dir in get_ancestor_directories(base_dir):
                    for op in ops:
                        rules.append(f"(deny {op}")
                        rules.append(f"  (literal {escape_path(ancestor_dir)})")
                        rules.append(f'  (with message "{log_tag}"))')
        else:
            for op in ops:
                rules.append(f"(deny {op}")
                rules.append(f"  (subpath {escape_path(normalized_path)})")
                rules.append(f'  (with message "{log_tag}"))')
            for ancestor_dir in get_ancestor_directories(normalized_path):
                for op in ops:
                    rules.append(f"(deny {op}")
                    rules.append(f"  (literal {escape_path(ancestor_dir)})")
                    rules.append(f'  (with message "{log_tag}"))')

    return rules


def generate_read_rules(
    config: FsReadRestrictionConfig | None,
    log_tag: str,
    write_allow_paths: list[str] | None = None,
) -> list[str]:
    """(allow file-read*) → (deny ...) → (allow ...) with move blocking."""
    if config is None:
        return ["(allow file-read*)"]

    rules: list[str] = []
    denies_root = False
    rules.append("(allow file-read*)")

    for path_pattern in config.get("denyOnly") or []:
        normalized_path = normalize_path_for_sandbox(path_pattern)
        if normalized_path == "/":
            denies_root = True
        if contains_glob_chars(normalized_path):
            regex_pattern = glob_to_regex(normalized_path)
            rules.append("(deny file-read*")
            rules.append(f"  (regex {escape_path(regex_pattern)})")
            rules.append(f'  (with message "{log_tag}"))')
        else:
            rules.append("(deny file-read*")
            rules.append(f"  (subpath {escape_path(normalized_path)})")
            rules.append(f'  (with message "{log_tag}"))')

    if denies_root:
        rules.append('(allow file-read* (literal "/"))')

    allowed_subpaths: list[str] = []
    for path_pattern in config.get("allowWithinDeny") or []:
        normalized_path = normalize_path_for_sandbox(path_pattern)
        if contains_glob_chars(normalized_path):
            regex_pattern = glob_to_regex(normalized_path)
            rules.append("(allow file-read*")
            rules.append(f"  (regex {escape_path(regex_pattern)})")
            rules.append(f'  (with message "{log_tag}"))')
        else:
            allowed_subpaths.append(normalized_path)
            rules.append("(allow file-read*")
            rules.append(f"  (subpath {escape_path(normalized_path)})")
            rules.append(f'  (with message "{log_tag}"))')

    for deny_path in config.get("denyOnly") or []:
        if contains_glob_chars(deny_path):
            continue
        normalized = normalize_path_for_sandbox(deny_path)
        if any(normalized.startswith(a + "/") for a in allowed_subpaths):
            rules.append("(deny file-read*")
            rules.append(f"  (subpath {escape_path(normalized)})")
            rules.append(f'  (with message "{log_tag}"))')

    if len(config.get("denyOnly") or []) > 0:
        rules.append("(allow file-read-metadata")
        rules.append("  (vnode-type DIRECTORY))")

    rules.extend(generate_move_blocking_rules(config.get("denyOnly") or [], log_tag))

    if write_allow_paths:
        for path_pattern in write_allow_paths:
            normalized_path = normalize_path_for_sandbox(path_pattern)
            for op in ("file-write-unlink", "file-write-create"):
                if contains_glob_chars(normalized_path):
                    regex_pattern = glob_to_regex(normalized_path)
                    rules.append(f"(allow {op}")
                    rules.append(f"  (regex {escape_path(regex_pattern)})")
                    rules.append(f'  (with message "{log_tag}"))')
                else:
                    rules.append(f"(allow {op}")
                    rules.append(f"  (subpath {escape_path(normalized_path)})")
                    rules.append(f'  (with message "{log_tag}"))')

    return rules


def generate_write_rules(
    config: FsWriteRestrictionConfig | None,
    log_tag: str,
    allow_git_config: bool = False,
) -> list[str]:
    """(allow file-write* ...) then (deny ...) with move blocking."""
    if config is None:
        return ["(allow file-write*)"]

    rules: list[str] = []

    for path_pattern in config.get("allowOnly") or []:
        normalized_path = normalize_path_for_sandbox(path_pattern)
        if contains_glob_chars(normalized_path):
            regex_pattern = glob_to_regex(normalized_path)
            rules.append("(allow file-write*")
            rules.append(f"  (regex {escape_path(regex_pattern)})")
            rules.append(f'  (with message "{log_tag}"))')
        else:
            rules.append("(allow file-write*")
            rules.append(f"  (subpath {escape_path(normalized_path)})")
            rules.append(f'  (with message "{log_tag}"))')

    deny_paths: list[str] = [
        *(config.get("denyWithinAllow") or []),
        *mac_get_mandatory_deny_patterns(allow_git_config),
    ]

    for path_pattern in deny_paths:
        normalized_path = normalize_path_for_sandbox(path_pattern)
        if contains_glob_chars(normalized_path):
            regex_pattern = glob_to_regex(normalized_path)
            rules.append("(deny file-write*")
            rules.append(f"  (regex {escape_path(regex_pattern)})")
            rules.append(f'  (with message "{log_tag}"))')
        else:
            rules.append("(deny file-write*")
            rules.append(f"  (subpath {escape_path(normalized_path)})")
            rules.append(f'  (with message "{log_tag}"))')

    rules.extend(generate_move_blocking_rules(deny_paths, log_tag))
    return rules


def generate_sandbox_profile(
    *,
    read_config: FsReadRestrictionConfig | None,
    write_config: FsWriteRestrictionConfig | None,
    http_proxy_port: int | None = None,
    socks_proxy_port: int | None = None,
    needs_network_restriction: bool,
    allow_unix_sockets: list[str] | None = None,
    allow_all_unix_sockets: bool = False,
    allow_local_binding: bool = False,
    allow_mach_lookup: list[str] | None = None,
    allow_pty: bool = False,
    allow_git_config: bool = False,
    enable_weaker_network_isolation: bool = False,
    allow_apple_events: bool = False,
    log_tag: str = "",
) -> str:
    """Generate the complete Seatbelt profile — line-for-line port of the
    upstream template (version header, process/mach/ipc/iokit/sysctl rules,
    network rules, read/write rules, pty)."""
    profile: list[str] = [
        "(version 1)",
        f'(deny default (with message "{log_tag}"))',
        "",
        f"; LogTag: {log_tag}",
        "",
        "; Essential permissions - based on Chrome sandbox policy",
        "; Process permissions",
        "(allow process-exec)",
        "(allow process-fork)",
        "(allow process-info* (target same-sandbox))",
        "(allow signal (target same-sandbox))",
        "(allow mach-priv-task-port (target same-sandbox))",
        "",
        "; User preferences",
        "(allow user-preference-read)",
        "",
        "; Mach IPC - specific services only (no wildcard)",
        "(allow mach-lookup",
        '  (global-name "com.apple.audio.systemsoundserver")',
        '  (global-name "com.apple.distributed_notifications@Uv3")',
        '  (global-name "com.apple.FontObjectsServer")',
        '  (global-name "com.apple.fonts")',
        '  (global-name "com.apple.logd")',
        '  (global-name "com.apple.lsd.mapdb")',
        '  (global-name "com.apple.PowerManagement.control")',
        '  (global-name "com.apple.system.logger")',
        '  (global-name "com.apple.system.notification_center")',
        '  (global-name "com.apple.system.opendirectoryd.libinfo")',
        '  (global-name "com.apple.system.opendirectoryd.membership")',
        '  (global-name "com.apple.bsd.dirhelper")',
        '  (global-name "com.apple.securityd.xpc")',
        '  (global-name "com.apple.coreservices.launchservicesd")',
        ")",
        "",
    ]

    if enable_weaker_network_isolation:
        profile.append(
            "; trustd.agent - needed for Go TLS certificate verification "
            "(weaker network isolation)"
        )
        profile.append('(allow mach-lookup (global-name "com.apple.trustd.agent"))')

    if allow_apple_events:
        profile.append(
            "; Apple Events - opt-in; needed for open/osascript to talk to "
            "other apps (appleeventsd)"
        )
        profile.append("(allow appleevent-send)")
        profile.append(
            '(allow mach-lookup (global-name "com.apple.coreservices.appleevents"))'
        )
        profile.append(
            "; Launch Services open requests need the lsopen operation plus, on"
        )
        profile.append(
            "; macOS 14/15, coreservicesd and the quarantine resolver - without"
        )
        profile.append(
            "; these open fails with -10822 kLSServerCommunicationErr or -54"
        )
        profile.append("(allow lsopen)")
        profile.append(
            '(allow mach-lookup (global-name "com.apple.CoreServices.coreservicesd"))'
        )
        profile.append(
            '(allow mach-lookup (global-name "com.apple.coreservices.quarantine-resolver"))'
        )

    if allow_mach_lookup:
        profile.append("; User-specified XPC/Mach services")
        for name in allow_mach_lookup:
            if name.endswith("*"):
                profile.append(
                    "(allow mach-lookup (global-name-prefix "
                    f"{escape_path(name[:-1])}))"
                )
            else:
                profile.append(
                    f"(allow mach-lookup (global-name {escape_path(name)}))"
                )

    profile.extend(
        [
            "",
            "; POSIX IPC - shared memory",
            "(allow ipc-posix-shm)",
            "",
            "; POSIX IPC - semaphores for Python multiprocessing",
            "(allow ipc-posix-sem)",
            "",
            "; IOKit - specific operations only",
            "(allow iokit-open",
            '  (iokit-registry-entry-class "IOSurfaceRootUserClient")',
            '  (iokit-registry-entry-class "RootDomainUserClient")',
            '  (iokit-user-client-class "IOSurfaceSendRight")',
            ")",
            "",
            "; IOKit properties",
            "(allow iokit-get-properties)",
            "",
            "; Specific safe system-sockets, doesn't allow network access",
            "(allow system-socket (require-all (socket-domain AF_SYSTEM) "
            "(socket-protocol 2)))",
            "",
            "; sysctl - specific sysctls only",
            "(allow sysctl-read",
            '  (sysctl-name "hw.activecpu")',
            '  (sysctl-name "hw.busfrequency_compat")',
            '  (sysctl-name "hw.byteorder")',
            '  (sysctl-name "hw.cacheconfig")',
            '  (sysctl-name "hw.cachelinesize_compat")',
            '  (sysctl-name "hw.cpufamily")',
            '  (sysctl-name "hw.cpufrequency")',
            '  (sysctl-name "hw.cpufrequency_compat")',
            '  (sysctl-name "hw.cputype")',
            '  (sysctl-name "hw.l1dcachesize_compat")',
            '  (sysctl-name "hw.l1icachesize_compat")',
            '  (sysctl-name "hw.l2cachesize_compat")',
            '  (sysctl-name "hw.l3cachesize_compat")',
            '  (sysctl-name "hw.logicalcpu")',
            '  (sysctl-name "hw.logicalcpu_max")',
            '  (sysctl-name "hw.machine")',
            '  (sysctl-name "hw.memsize")',
            '  (sysctl-name "hw.ncpu")',
            '  (sysctl-name "hw.nperflevels")',
            '  (sysctl-name "hw.packages")',
            '  (sysctl-name "hw.pagesize_compat")',
            '  (sysctl-name "hw.pagesize")',
            '  (sysctl-name "hw.physicalcpu")',
            '  (sysctl-name "hw.physicalcpu_max")',
            '  (sysctl-name "hw.tbfrequency_compat")',
            '  (sysctl-name "hw.vectorunit")',
            '  (sysctl-name "kern.argmax")',
            '  (sysctl-name "kern.bootargs")',
            '  (sysctl-name "kern.hostname")',
            '  (sysctl-name "kern.maxfiles")',
            '  (sysctl-name "kern.maxfilesperproc")',
            '  (sysctl-name "kern.maxproc")',
            '  (sysctl-name "kern.ngroups")',
            '  (sysctl-name "kern.osproductversion")',
            '  (sysctl-name "kern.osrelease")',
            '  (sysctl-name "kern.ostype")',
            '  (sysctl-name "kern.osvariant_status")',
            '  (sysctl-name "kern.osversion")',
            '  (sysctl-name "kern.secure_kernel")',
            '  (sysctl-name "kern.tcsm_available")',
            '  (sysctl-name "kern.tcsm_enable")',
            '  (sysctl-name "kern.usrstack64")',
            '  (sysctl-name "kern.version")',
            '  (sysctl-name "kern.willshutdown")',
            '  (sysctl-name "machdep.cpu.brand_string")',
            '  (sysctl-name "machdep.ptrauth_enabled")',
            '  (sysctl-name "security.mac.lockdown_mode_state")',
            '  (sysctl-name "sysctl.proc_cputype")',
            '  (sysctl-name "vm.loadavg")',
            '  (sysctl-name-prefix "hw.optional.arm")',
            '  (sysctl-name-prefix "hw.optional.arm.")',
            '  (sysctl-name-prefix "hw.optional.armv8_")',
            '  (sysctl-name-prefix "hw.perflevel")',
            '  (sysctl-name-prefix "kern.proc.all")',
            '  (sysctl-name-prefix "kern.proc.pgrp.")',
            '  (sysctl-name-prefix "kern.proc.pid.")',
            '  (sysctl-name-prefix "machdep.cpu.")',
            '  (sysctl-name-prefix "net.routetable.")',
            ")",
            "",
            "; V8 thread calculations",
            "(allow sysctl-write",
            '  (sysctl-name "kern.tcsm_enable")',
            ")",
            "",
            "; Distributed notifications",
            "(allow distributed-notification-post)",
            "",
            "; Specific mach-lookup permissions for security operations",
            '(allow mach-lookup (global-name "com.apple.SecurityServer"))',
            "",
            "; File I/O on device files",
            '(allow file-ioctl (literal "/dev/null"))',
            '(allow file-ioctl (literal "/dev/zero"))',
            '(allow file-ioctl (literal "/dev/random"))',
            '(allow file-ioctl (literal "/dev/urandom"))',
            '(allow file-ioctl (literal "/dev/dtracehelper"))',
            '(allow file-ioctl (literal "/dev/tty"))',
            "",
            "(allow file-ioctl file-read-data file-write-data",
            "  (require-all",
            '    (literal "/dev/null")',
            "    (vnode-type CHARACTER-DEVICE)",
            "  )",
            ")",
            "",
        ]
    )

    profile.append("; Network")
    if not needs_network_restriction:
        profile.append("(allow network*)")
    else:
        if allow_local_binding:
            profile.append('(allow network-bind (local ip "*:*"))')
            profile.append('(allow network-inbound (local ip "*:*"))')
            profile.append('(allow network-outbound (remote ip "localhost:*"))')
        if allow_all_unix_sockets:
            profile.append("(allow system-socket (socket-domain AF_UNIX))")
            profile.append(
                '(allow network-bind (local unix-socket (path-regex #"^/")))'
            )
            profile.append(
                '(allow network-outbound (remote unix-socket (path-regex #"^/")))'
            )
        elif allow_unix_sockets:
            profile.append("(allow system-socket (socket-domain AF_UNIX))")
            for socket_path in allow_unix_sockets:
                normalized_path = normalize_path_for_sandbox(socket_path)
                profile.append(
                    "(allow network-bind (local unix-socket "
                    f"(subpath {escape_path(normalized_path)})))"
                )
                profile.append(
                    "(allow network-outbound (remote unix-socket "
                    f"(subpath {escape_path(normalized_path)})))"
                )
        if http_proxy_port is not None:
            profile.append(
                f'(allow network-bind (local ip "localhost:{http_proxy_port}"))'
            )
            profile.append(
                f'(allow network-inbound (local ip "localhost:{http_proxy_port}"))'
            )
            profile.append(
                f'(allow network-outbound (remote ip "localhost:{http_proxy_port}"))'
            )
        if socks_proxy_port is not None and socks_proxy_port != http_proxy_port:
            profile.append(
                f'(allow network-bind (local ip "localhost:{socks_proxy_port}"))'
            )
            profile.append(
                f'(allow network-inbound (local ip "localhost:{socks_proxy_port}"))'
            )
            profile.append(
                f'(allow network-outbound (remote ip "localhost:{socks_proxy_port}"))'
            )
    profile.append("")

    write_allow_paths = (
        write_config.get("allowOnly") if write_config is not None else None
    )
    profile.append("; File read")
    profile.extend(generate_read_rules(read_config, log_tag, write_allow_paths))
    profile.append("")
    profile.append("; File write")
    profile.extend(generate_write_rules(write_config, log_tag, allow_git_config))

    if allow_pty:
        profile.append("")
        profile.append("; Pseudo-terminal (pty) support")
        profile.append("(allow pseudo-tty)")
        profile.append("(allow file-ioctl")
        profile.append('  (literal "/dev/ptmx")')
        profile.append('  (regex #"^/dev/ttys")')
        profile.append(")")
        profile.append("(allow file-read* file-write*")
        profile.append('  (literal "/dev/ptmx")')
        profile.append('  (regex #"^/dev/ttys")')
        profile.append(")")

    return "\n".join(profile)


def wrap_command_with_sandbox_macos(
    *,
    command: str,
    needs_network_restriction: bool,
    http_proxy_port: int | None = None,
    socks_proxy_port: int | None = None,
    proxy_auth_token: str | None = None,
    ca_cert_path: str | None = None,
    allow_unix_sockets: list[str] | None = None,
    allow_all_unix_sockets: bool = False,
    allow_local_binding: bool = False,
    allow_mach_lookup: list[str] | None = None,
    read_config: FsReadRestrictionConfig | None = None,
    write_config: FsWriteRestrictionConfig | None = None,
    unset_env_vars: list[str] | None = None,
    set_env_vars: dict[str, str] | None = None,
    masked_file_binds: list[dict[str, str]] | None = None,
    ignore_violations: dict[str, list[str]] | None = None,
    allow_pty: bool = False,
    allow_git_config: bool = False,
    git_safe_directories: list[str] | None = None,
    enable_weaker_network_isolation: bool = False,
    allow_apple_events: bool = False,
    bin_shell: str | None = None,
) -> list[str]:
    """Build the sandbox-exec argv for one sandboxed command.

    ADAPT: returns an argv list for direct spawn. The profile string is
    generated line-for-line from the upstream template. Credential masks
    degrade to read-deny (upstream behavior before the DYLD interposer).
    ``enableWeakerNetworkIsolation`` is always false in production (config
    rejects it) but kept for profile parity.
    """
    del ignore_violations  # reserved upstream param; unused in wrap
    if enable_weaker_network_isolation:
        raise ValueError(
            "enableWeakerNetworkIsolation is not exposed as a production "
            "weakening switch"
        )

    read_config_eff = read_config
    if masked_file_binds:
        log_for_debugging(
            "[Sandbox macOS] file mask degrades to deny on macOS until the "
            "interposer lands"
        )
        read_config_eff = {
            "denyOnly": [
                *(read_config.get("denyOnly") if read_config else []),
                *(b["realPath"] for b in masked_file_binds),
            ],
            "allowWithinDeny": (
                read_config.get("allowWithinDeny") if read_config else None
            ),
        }

    has_read_restrictions = bool(
        read_config_eff and len(read_config_eff.get("denyOnly") or []) > 0
    )
    has_write_restrictions = write_config is not None
    has_env_restrictions = bool(unset_env_vars) or bool(set_env_vars)
    has_git_config = bool(git_safe_directories)

    if (
        not needs_network_restriction
        and not has_read_restrictions
        and not has_write_restrictions
        and not has_env_restrictions
        and not has_git_config
    ):
        return ["bash", "-c", command]

    log_tag = generate_log_tag(command)

    profile = generate_sandbox_profile(
        read_config=read_config_eff,
        write_config=write_config,
        http_proxy_port=http_proxy_port,
        socks_proxy_port=socks_proxy_port,
        needs_network_restriction=needs_network_restriction,
        allow_unix_sockets=allow_unix_sockets,
        allow_all_unix_sockets=allow_all_unix_sockets,
        allow_local_binding=allow_local_binding,
        allow_mach_lookup=allow_mach_lookup,
        allow_pty=allow_pty,
        allow_git_config=allow_git_config,
        enable_weaker_network_isolation=enable_weaker_network_isolation,
        allow_apple_events=allow_apple_events,
        log_tag=log_tag,
    )

    proxy_env_args = generate_proxy_env_vars(
        http_proxy_port,
        socks_proxy_port,
        ca_cert_path,
        proxy_auth_token,
        write_config is None,
    )

    if allow_local_binding and needs_network_restriction:
        flag = "-Djava.net.preferIPv4Stack=true"
        denied = bool(unset_env_vars and "JAVA_TOOL_OPTIONS" in unset_env_vars)
        inherited = "" if denied else os.environ.get("JAVA_TOOL_OPTIONS", "")
        value = inherited if flag in inherited else " ".join(
            [v for v in (inherited, flag) if v]
        )
        proxy_env_args.append(f"JAVA_TOOL_OPTIONS={value}")

    if git_safe_directories:
        git_cfg = build_posix_git_safe_dir_env(
            git_safe_directories, unset_env_vars, set_env_vars
        )
        for name, value in git_cfg.items():
            proxy_env_args.append(f"{name}={value}")

    shell_name = bin_shell or "bash"
    shell = which(shell_name)
    if not shell:
        raise RuntimeError(f"Shell '{shell_name}' not found in PATH")

    unset_env_args: list[str] = []
    for name in unset_env_vars or []:
        unset_env_args.extend(["-u", name])
    set_env_args = [f"{name}={value}" for name, value in (set_env_vars or {}).items()]

    return [
        "env",
        *unset_env_args,
        *set_env_args,
        *proxy_env_args,
        "/usr/bin/sandbox-exec",
        "-p",
        profile,
        shell,
        "-c",
        command,
    ]


# ---------------------------------------------------------------------------
# startMacOSSandboxLogMonitor
# ---------------------------------------------------------------------------

def start_macos_sandbox_log_monitor(
    callback: SandboxViolationCallback,
    ignore_violations: dict[str, list[str]] | None = None,
) -> Callable[[], None]:
    """Stream unified logs for Seatbelt denials tagged with this session
    suffix. macOS-only; returns a stop callable. ADAPT: asyncio subprocess;
    production never enables it on non-macOS hosts."""
    cmd_extract_regex = re.compile(r"CMD64_(.+?)_END")
    sandbox_extract_regex = re.compile(r"Sandbox:\s+(.+)$")

    wildcard_paths = (ignore_violations or {}).get("*") or []
    command_patterns = [
        (pattern, paths)
        for pattern, paths in (ignore_violations or {}).items()
        if pattern != "*"
    ]

    def _handle_line(line: str) -> None:
        violation_match = sandbox_extract_regex.search(line)
        if not violation_match or "deny" not in line or "Sandbox:" not in line:
            return
        violation_details = violation_match.group(1)

        command: str | None = None
        encoded_command: str | None = None
        cmd_match = cmd_extract_regex.search(line)
        if cmd_match:
            encoded_command = cmd_match.group(1)
            try:
                command = decode_sandboxed_command(encoded_command)
            except Exception:
                pass

        if (
            "mDNSResponder" in violation_details
            or "mach-lookup com.apple.diagnosticd" in violation_details
            or "mach-lookup com.apple.analyticsd" in violation_details
        ):
            return

        if ignore_violations and command:
            if wildcard_paths and any(
                path in violation_details for path in wildcard_paths
            ):
                return
            for pattern, paths in command_patterns:
                if pattern in command and any(
                    path in violation_details for path in paths
                ):
                    return

        callback(
            SandboxViolationEvent(
                line=violation_details,
                command=command,
                encodedCommand=encoded_command,
                timestamp=_dt.datetime.now(_dt.timezone.utc),
            )
        )

    process: asyncio.subprocess.Process | None = None
    stop_event: asyncio.Event | None = None

    async def _run() -> None:
        nonlocal process, stop_event
        stop_event = asyncio.Event()
        try:
            process = await asyncio.create_subprocess_exec(
                "log",
                "stream",
                "--predicate",
                f'(eventMessage ENDSWITH "{_session_suffix}")',
                "--style",
                "compact",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            log_for_debugging(
                f"[Sandbox Monitor] Failed to start log stream: {error}"
            )
            return
        assert process.stdout is not None
        assert process.stderr is not None
        reader_task = asyncio.ensure_future(
            _drain(process.stdout, stop_event)
        )
        stderr_task = asyncio.ensure_future(
            _drain_stderr(process.stderr, stop_event)
        )
        await stop_event.wait()
        reader_task.cancel()
        stderr_task.cancel()
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        await asyncio.gather(reader_task, stderr_task, return_exceptions=True)

    async def _drain(
        stream: asyncio.StreamReader, stop: asyncio.Event
    ) -> None:
        pending = ""
        while not stop.is_set():
            try:
                chunk = await stream.read(4096)
            except (ConnectionError, OSError):
                break
            if not chunk:
                break
            pending += chunk.decode("utf-8", errors="replace")
            while "\n" in pending:
                line, pending = pending.split("\n", 1)
                _handle_line(line)

    async def _drain_stderr(
        stream: asyncio.StreamReader, stop: asyncio.Event
    ) -> None:
        while not stop.is_set():
            try:
                chunk = await stream.read(4096)
            except (ConnectionError, OSError):
                break
            if not chunk:
                break
            log_for_debugging(
                f"[Sandbox Monitor] Log stream stderr: "
                f"{chunk.decode('utf-8', errors='replace')}"
            )

    def _stop() -> None:
        log_for_debugging("[Sandbox Monitor] Stopping log monitor")
        if stop_event is not None:
            stop_event.set()

    asyncio.ensure_future(_run())

    return _stop
