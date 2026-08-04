"""SRT Linux sandbox — bubblewrap argv generation, socat network bridge,
mandatory deny scan, bwrap mount-point cleanup, seccomp nesting, and the
filesystem violation monitor.

Source: sandbox-runtime@0.0.67 ``src/sandbox/{linux-sandbox-utils,linux-violation-monitor}.ts``
Repository: anthropics/sandbox-runtime @ 21d8f75e1bc00eede09b3103e68b2eae097110d1
License: Apache-2.0 (retained under the native sandbox license directory)

Host delta (ADAPT, per G0 map §4.1): ``wrapCommandWithSandboxLinux`` returns
an argv list (bwrap + args) instead of a shell-quoted string — the Python
manager spawns bwrap directly with ``shell=False``; the inner sandbox
command string keeps the exact upstream shell construction (socat listeners
+ apply-seccomp prefix + user command), built with the ported shell-quote.
``initializeLinuxNetworkBridge`` uses asyncio subprocesses in a new process
group (start_new_session) so bridge cleanup can kill the tree. Credential
mask binds (maskedFileBinds/maskedFileStoreDir) and the observe-socket env
plumbing are kept as seams but never populated (credentials rejected).
"""
from __future__ import annotations

import asyncio
import atexit
import json
import os
import re
import shutil
import tempfile
from typing import Any

from .policy import (
    DANGEROUS_DIRECTORIES,
    DANGEROUS_FILES,
    FsReadRestrictionConfig,
    FsWriteRestrictionConfig,
    build_posix_git_safe_dir_env,
    decode_sandboxed_command,
    encode_sandboxed_command,
    generate_proxy_env_vars,
    get_dangerous_directories,
    is_symlink_outside_boundary,
    normalize_case_for_comparison,
    normalize_path_for_sandbox,
)
from .process import log_for_debugging, ripgrep, shell_quote, which
from .seccomp import get_apply_seccomp_binary_path
from .macos import SandboxViolationCallback, SandboxViolationEvent  # noqa: F401  (type re-export)

DEFAULT_MANDATORY_DENY_SEARCH_DEPTH = 3

MAX_SYMLINK_RESOLUTION_DEPTH = 40

_BWRAP_MOUNT_POINTS: set[str] = set()
_active_sandbox_count = 0
_exit_handler_registered = False


class LinuxNetworkBridgeContext:
    def __init__(
        self,
        http_socket_path: str,
        socks_socket_path: str,
        http_bridge_process: asyncio.subprocess.Process,
        socks_bridge_process: asyncio.subprocess.Process,
        http_proxy_port: int,
        socks_proxy_port: int,
    ) -> None:
        self.http_socket_path = http_socket_path
        self.socks_socket_path = socks_socket_path
        self.http_bridge_process = http_bridge_process
        self.socks_bridge_process = socks_bridge_process
        self.http_proxy_port = http_proxy_port
        self.socks_proxy_port = socks_proxy_port


# ---------------------------------------------------------------------------
# bwrap mount-point cleanup (upstream module state + exit handler)
# ---------------------------------------------------------------------------

def _register_exit_cleanup_handler() -> None:
    global _exit_handler_registered
    if _exit_handler_registered:
        return
    atexit.register(lambda: cleanup_bwrap_mount_points(force=True))
    _exit_handler_registered = True


def cleanup_bwrap_mount_points(*, force: bool = False) -> None:
    """Remove empty mount-point files bwrap created for non-existent denies.

    File deletion is deferred while other sandboxes are active (deleting a
    mount point on the host detaches the live bind). ``force`` (process
    exit, reset) deletes unconditionally.
    """
    global _active_sandbox_count
    if not force:
        if _active_sandbox_count > 0:
            _active_sandbox_count -= 1
        if _active_sandbox_count > 0:
            log_for_debugging(
                "[Sandbox Linux] Deferring mount point cleanup — "
                f"{_active_sandbox_count} sandbox(es) still active"
            )
            return
    else:
        _active_sandbox_count = 0

    for mount_point in list(_BWRAP_MOUNT_POINTS):
        try:
            stat = os.stat(mount_point)
            if stat.st_mode & 0o170000 == 0o100000 and stat.st_size == 0:
                os.unlink(mount_point)
                log_for_debugging(
                    "[Sandbox Linux] Cleaned up bwrap mount point (file): "
                    f"{mount_point}"
                )
            elif stat.st_mode & 0o170000 == 0o40000:
                if not os.listdir(mount_point):
                    os.rmdir(mount_point)
                    log_for_debugging(
                        "[Sandbox Linux] Cleaned up bwrap mount point (dir): "
                        f"{mount_point}"
                    )
        except OSError:
            pass
    _BWRAP_MOUNT_POINTS.clear()


# ---------------------------------------------------------------------------
# symlink/path helpers (upstream linux-sandbox-utils)
# ---------------------------------------------------------------------------

def find_symlink_in_path(
    target_path: str, allowed_write_paths: list[str]
) -> str | None:
    """First symlink component within an allowed write path, else None."""
    parts = target_path.split(os.sep)
    current_path = ""
    for part in parts:
        if not part:
            continue
        next_path = current_path + os.sep + part
        try:
            if os.path.islink(next_path):
                is_within = any(
                    next_path.startswith(allowed + "/") or next_path == allowed
                    for allowed in allowed_write_paths
                )
                if is_within:
                    return next_path
        except OSError:
            break
        current_path = next_path
    return None


def resolve_symlinked_deny_path(target_path: str) -> str | None:
    """Canonicalize a deny path through symlinks (resolve-before-mask).

    Returns None when the path cannot be canonicalized (symlink cycle /
    chain past the ELOOP bound) — callers skip such paths rather than emit
    a mask bwrap would reject.
    """
    current = target_path
    for _ in range(MAX_SYMLINK_RESOLUTION_DEPTH):
        try:
            return os.path.realpath(current)
        except OSError:
            pass

        ancestor = current
        remainder: list[str] = []
        resolved_ancestor: str | None = None
        while resolved_ancestor is None:
            parent = os.path.dirname(ancestor)
            if parent == ancestor:
                return None
            remainder.insert(0, os.path.basename(ancestor))
            ancestor = parent
            try:
                resolved_ancestor = os.path.realpath(ancestor)
            except OSError:
                pass

        first_missing = os.path.join(resolved_ancestor, remainder[0])
        link_target: str | None = None
        try:
            link_target = os.readlink(first_missing)
        except OSError:
            pass
        if link_target is None:
            return os.path.join(resolved_ancestor, *remainder)
        current = os.path.join(
            os.path.normpath(os.path.join(os.path.dirname(first_missing), link_target)),
            *remainder[1:],
        )
    return None


def has_file_ancestor(target_path: str) -> bool:
    """True when any existing component is a file/symlink (nothing below it
    can be created) — the git-worktree .git-is-a-file case."""
    parts = target_path.split(os.sep)
    current_path = ""
    for part in parts:
        if not part:
            continue
        next_path = current_path + os.sep + part
        try:
            if os.path.isfile(next_path) or os.path.islink(next_path):
                return True
        except OSError:
            break
        current_path = next_path
    return False


def find_first_nonexistent_component(target_path: str) -> str:
    parts = target_path.split(os.sep)
    current_path = ""
    for part in parts:
        if not part:
            continue
        next_path = current_path + os.sep + part
        if not os.path.exists(next_path):
            return next_path
        current_path = next_path
    return target_path


def resolve_symlink_deny_dest(normalized_path: str) -> str:
    """File read-deny binds target the symlink's resolved target (bwrap
    rejects symlink bind destinations)."""
    try:
        if os.path.islink(normalized_path):
            return os.path.realpath(normalized_path)
    except OSError:
        pass
    return normalized_path


# ---------------------------------------------------------------------------
# mandatory deny scan (linuxGetMandatoryDenyPaths)
# ---------------------------------------------------------------------------

async def linux_get_mandatory_deny_paths(
    cwd: str,
    ripgrep_config: dict[str, Any] | None = None,
    max_depth: int = DEFAULT_MANDATORY_DENY_SEARCH_DEPTH,
    allow_git_config: bool = False,
    abort_signal: asyncio.Future | None = None,
) -> list[str]:
    """Single ripgrep call with --iglob patterns; returns concrete deny
    paths for bwrap (Linux only)."""
    rg = ripgrep_config or {"command": "rg"}
    dangerous_directories = get_dangerous_directories()

    deny_paths: list[str] = [
        *(os.path.join(cwd, f) for f in DANGEROUS_FILES),
        *(os.path.join(cwd, d) for d in dangerous_directories),
    ]

    dot_git_path = os.path.join(cwd, ".git")
    dot_git_is_directory = False
    try:
        dot_git_is_directory = os.path.isdir(dot_git_path)
    except OSError:
        pass

    if dot_git_is_directory:
        deny_paths.append(os.path.join(cwd, ".git/hooks"))
        if not allow_git_config:
            deny_paths.append(os.path.join(cwd, ".git/config"))

    iglob_args: list[str] = []
    for file_name in DANGEROUS_FILES:
        iglob_args.append("--iglob")
        iglob_args.append(file_name)
    for dir_name in dangerous_directories:
        iglob_args.append("--iglob")
        iglob_args.append(f"**/{dir_name}/**")
    iglob_args.append("--iglob")
    iglob_args.append("**/.git/hooks/**")
    if not allow_git_config:
        iglob_args.append("--iglob")
        iglob_args.append("**/.git/config")

    matches: list[str] = []
    try:
        matches = await ripgrep(
            [
                "--files",
                "--hidden",
                "--max-depth",
                str(max_depth),
                *iglob_args,
                "-g",
                "!**/node_modules/**",
            ],
            cwd,
            abort_signal,
            command=rg.get("command", "rg"),
            command_args=rg.get("args"),
            argv0=rg.get("argv0"),
        )
    except Exception as error:  # noqa: BLE001 — upstream logs and continues
        log_for_debugging(f"[Sandbox] ripgrep scan failed: {error}")

    for match in matches:
        absolute_path = os.path.normpath(os.path.join(cwd, match))

        found_dir = False
        for dir_name in [*dangerous_directories, ".git"]:
            normalized_dir_name = normalize_case_for_comparison(dir_name)
            segments = absolute_path.split(os.sep)
            dir_index = next(
                (
                    i
                    for i, s in enumerate(segments)
                    if normalize_case_for_comparison(s) == normalized_dir_name
                ),
                -1,
            )
            if dir_index != -1:
                if dir_name == ".git":
                    git_dir = os.sep.join(segments[: dir_index + 1])
                    if ".git/hooks" in match:
                        deny_paths.append(os.path.join(git_dir, "hooks"))
                    elif ".git/config" in match:
                        deny_paths.append(os.path.join(git_dir, "config"))
                else:
                    deny_paths.append(os.sep.join(segments[: dir_index + 1]))
                found_dir = True
                break

        if not found_dir:
            deny_paths.append(absolute_path)

    return list(dict.fromkeys(deny_paths))


# ---------------------------------------------------------------------------
# dependency checks (getLinuxDependencyStatus / checkLinuxDependencies)
# ---------------------------------------------------------------------------

def _is_executable(p: str) -> bool:
    return os.access(p, os.X_OK)


def get_linux_dependency_status(
    seccomp_config: dict[str, Any] | None = None,
    bwrap_path: str | None = None,
    socat_path: str | None = None,
) -> dict[str, bool]:
    return {
        "hasBwrap": (
            _is_executable(bwrap_path) if bwrap_path else which("bwrap") is not None
        ),
        "hasSocat": (
            _is_executable(socat_path) if socat_path else which("socat") is not None
        ),
        "hasSeccompApply": (
            True
            if (seccomp_config or {}).get("argv0")
            else get_apply_seccomp_binary_path(
                (seccomp_config or {}).get("applyPath")
            )
            is not None
        ),
    }


def check_linux_dependencies(
    seccomp_config: dict[str, Any] | None = None,
    bwrap_path: str | None = None,
    socat_path: str | None = None,
) -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if bwrap_path:
        if not _is_executable(bwrap_path):
            errors.append(f"bubblewrap (bwrap) not executable at {bwrap_path}")
    elif which("bwrap") is None:
        errors.append("bubblewrap (bwrap) not installed")

    if socat_path:
        if not _is_executable(socat_path):
            errors.append(f"socat not executable at {socat_path}")
    elif which("socat") is None:
        errors.append("socat not installed")

    if not (seccomp_config or {}).get("argv0") and (
        get_apply_seccomp_binary_path((seccomp_config or {}).get("applyPath"))
        is None
    ):
        warnings.append(
            "seccomp not available - unix socket access not restricted"
        )

    return {"warnings": warnings, "errors": errors}


# ---------------------------------------------------------------------------
# network bridge (initializeLinuxNetworkBridge)
# ---------------------------------------------------------------------------

def _bridge_socat_args(
    listen_path: str, target_port: int
) -> list[str]:
    return [
        f"UNIX-LISTEN:{listen_path},fork,reuseaddr,mode=0600",
        (
            f"TCP:localhost:{target_port},keepalive,keepidle=10,"
            "keepintvl=5,keepcnt=3"
        ),
    ]


async def _wait_for_bridge_sockets(
    http_socket_path: str,
    socks_socket_path: str,
    http_bridge: asyncio.subprocess.Process,
    socks_bridge: asyncio.subprocess.Process,
) -> None:
    max_attempts = 5
    for attempt in range(max_attempts):
        if (
            http_bridge.returncode is not None
            or socks_bridge.returncode is not None
        ):
            raise RuntimeError("Linux bridge process died unexpectedly")
        if os.path.exists(http_socket_path) and os.path.exists(
            socks_socket_path
        ):
            log_for_debugging(
                f"Linux bridges ready after {attempt + 1} attempts"
            )
            return
        if attempt == max_attempts - 1:
            raise RuntimeError(
                f"Failed to create bridge sockets after {max_attempts} attempts"
            )
        await asyncio.sleep(attempt * 0.1)


async def initialize_linux_network_bridge(
    http_proxy_port: int,
    socks_proxy_port: int,
    socat_path: str | None = None,
) -> LinuxNetworkBridgeContext:
    """Start socat Unix-socket bridges from the bwrap namespace to the host
    proxies. When both protocols share one mux port, the SOCKS side reuses
    the HTTP bridge."""
    socat = socat_path or "socat"
    socket_id = os.urandom(8).hex()
    http_socket_path = os.path.join(
        tempfile.gettempdir(), f"claude-http-{socket_id}.sock"
    )
    socks_socket_path = os.path.join(
        tempfile.gettempdir(), f"claude-socks-{socket_id}.sock"
    )

    async def _spawn_bridge(args: list[str], label: str) -> asyncio.subprocess.Process:
        log_for_debugging(f"Starting {label} bridge: {socat} {' '.join(args)}")
        try:
            return await asyncio.create_subprocess_exec(
                socat,
                *args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as error:
            raise RuntimeError(
                f"Failed to start {label} bridge process: {error}"
            ) from error

    http_bridge = await _spawn_bridge(
        _bridge_socat_args(http_socket_path, http_proxy_port), "HTTP"
    )

    if socks_proxy_port == http_proxy_port:
        socks_bridge = http_bridge
        socks_sock_path = http_socket_path
    else:
        try:
            socks_bridge = await _spawn_bridge(
                _bridge_socat_args(socks_socket_path, socks_proxy_port),
                "SOCKS",
            )
        except Exception:
            _kill_bridge_process_tree(http_bridge)
            raise
        socks_sock_path = socks_socket_path

    try:
        await _wait_for_bridge_sockets(
            http_socket_path, socks_sock_path, http_bridge, socks_bridge
        )
    except Exception:
        await _terminate_bridge(http_bridge)
        if socks_bridge is not http_bridge:
            await _terminate_bridge(socks_bridge)
        raise

    return LinuxNetworkBridgeContext(
        http_socket_path=http_socket_path,
        socks_socket_path=socks_sock_path,
        http_bridge_process=http_bridge,
        socks_bridge_process=socks_bridge,
        http_proxy_port=http_proxy_port,
        socks_proxy_port=socks_proxy_port,
    )


async def _terminate_bridge(process: asyncio.subprocess.Process) -> None:
    """SIGTERM the whole bridge process group, then SIGKILL after a bounded
    wait (upstream BRIDGE_EXIT_TIMEOUT_MS=1500)."""
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, 15)  # SIGTERM
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=1.5)
        return
    except asyncio.TimeoutError:
        _kill_bridge_process_tree(process)


def _kill_bridge_process_tree(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, 9)  # SIGKILL
    except ProcessLookupError:
        pass
    except PermissionError:
        try:
            process.kill()
        except ProcessLookupError:
            pass


async def stop_linux_network_bridge(
    bridge: LinuxNetworkBridgeContext,
) -> None:
    """Kill both bridges and remove bridge sockets (upstream reset path)."""
    await asyncio.gather(
        _terminate_bridge(bridge.http_bridge_process),
        _terminate_bridge(bridge.socks_bridge_process),
        return_exceptions=True,
    )
    for socket_path in {
        bridge.http_socket_path,
        bridge.socks_socket_path,
    }:
        try:
            os.unlink(socket_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# apply-seccomp prefix resolution (resolveApplySeccompPrefix)
# ---------------------------------------------------------------------------

def resolve_apply_seccomp_prefix(
    apply_path: str | None, argv0: str | None
) -> str | None:
    """Shell-ready prefix ending in a trailing space; None when seccomp is
    unavailable. argv0 mode trusts applyPath verbatim (no existence check)."""
    if argv0:
        if not apply_path:
            raise ValueError("seccompConfig.argv0 requires seccompConfig.applyPath")
        return f"ARGV0={shell_quote([argv0])} {shell_quote([apply_path])} "
    binary = get_apply_seccomp_binary_path(apply_path)
    return f"{shell_quote([binary])} " if binary else None


# ---------------------------------------------------------------------------
# sandbox command builder (buildSandboxCommand)
# ---------------------------------------------------------------------------

def build_sandbox_command(
    http_socket_path: str,
    socks_socket_path: str,
    user_command: str,
    apply_seccomp_prefix: str | None,
    shell: str = "bash",
    socat_path: str | None = None,
) -> str:
    socat = shell_quote([socat_path or "socat"])
    socat_commands = [
        f"{socat} TCP-LISTEN:3128,fork,reuseaddr UNIX-CONNECT:{http_socket_path} >/dev/null 2>&1 &",
        f"{socat} TCP-LISTEN:1080,fork,reuseaddr UNIX-CONNECT:{socks_socket_path} >/dev/null 2>&1 &",
        'trap "kill %1 %2 2>/dev/null; exit" EXIT',
    ]
    if apply_seccomp_prefix:
        apply_seccomp_cmd = (
            apply_seccomp_prefix + shell_quote([shell, "-c", user_command])
        )
        inner_script = "\n".join([*socat_commands, apply_seccomp_cmd])
    else:
        inner_script = "\n".join(
            [*socat_commands, f"eval {shell_quote([user_command])}"]
        )
    return f"{shell} -c {shell_quote([inner_script])}"


# ---------------------------------------------------------------------------
# filesystem bwrap args (generateFilesystemArgs)
# ---------------------------------------------------------------------------

def _push_read_deny_dir_mounts(
    args: list[str],
    normalized_path: str,
    allowed_write_paths: list[str],
    read_allow_paths: list[str],
) -> None:
    deny_sep = "/" if normalized_path == "/" else normalized_path + "/"
    args.append("--tmpfs")
    args.append(normalized_path)

    for write_path in allowed_write_paths:
        if write_path.startswith(deny_sep) or write_path == normalized_path:
            args.append("--bind")
            args.append(write_path)
            args.append(write_path)
            log_for_debugging(
                "[Sandbox Linux] Re-bound write path wiped by denyRead "
                f"tmpfs: {write_path}"
            )

    for allow_path in read_allow_paths:
        if not (allow_path.startswith(deny_sep) or allow_path == normalized_path):
            continue
        if not os.path.exists(allow_path):
            log_for_debugging(
                "[Sandbox Linux] Skipping non-existent read allow path: "
                f"{allow_path}"
            )
            continue
        if any(
            (w.startswith(deny_sep) or w == normalized_path)
            and (allow_path == w or allow_path.startswith(w + "/"))
            for w in allowed_write_paths
        ):
            continue
        args.append("--ro-bind")
        args.append(allow_path)
        args.append(allow_path)
        log_for_debugging(
            "[Sandbox Linux] Re-allowed read access within denied region: "
            f"{allow_path}"
        )


async def generate_filesystem_args(
    read_config: FsReadRestrictionConfig | None,
    write_config: FsWriteRestrictionConfig | None,
    masked_file_binds: list[dict[str, str]] | None = None,
    masked_file_store_dir: str | None = None,
    ripgrep_config: dict[str, Any] | None = None,
    mandatory_deny_search_depth: int = DEFAULT_MANDATORY_DENY_SEARCH_DEPTH,
    allow_git_config: bool = False,
    abort_signal: asyncio.Future | None = None,
    cwd: str | None = None,
) -> list[str]:
    """bwrap filesystem bind args — exact port of the upstream ordering:
    root ro-bind/write binds, denyWrite buffered, denyRead tmpfs/masks,
    masked-file binds, then denyWrite emission with tmpfs/mask re-application.
    """
    args: list[str] = []
    allowed_write_paths: list[str] = []
    deny_write_args: list[str] = []
    deny_write_raw_dests: dict[str, str] = {}
    cwd = cwd or os.getcwd()

    if write_config is not None:
        args.append("--ro-bind")
        args.append("/")
        args.append("/")

        for path_pattern in write_config.get("allowOnly") or []:
            normalized_path = normalize_path_for_sandbox(path_pattern)
            log_for_debugging(
                f"[Sandbox Linux] Processing write path: {path_pattern} -> {normalized_path}"
            )
            if normalized_path.startswith("/dev/"):
                log_for_debugging(
                    f"[Sandbox Linux] Skipping /dev path: {normalized_path}"
                )
                continue
            if not os.path.exists(normalized_path):
                log_for_debugging(
                    "[Sandbox Linux] Skipping non-existent write path: "
                    f"{normalized_path}"
                )
                continue
            try:
                resolved_path = os.path.realpath(normalized_path)
                normalized_for_comparison = re.sub(r"/+$", "", normalized_path)

                if (
                    resolved_path != normalized_for_comparison
                    and is_symlink_outside_boundary(
                        normalized_path, resolved_path
                    )
                ):
                    log_for_debugging(
                        "[Sandbox Linux] Skipping symlink write path pointing "
                        f"outside expected location: {path_pattern} -> {resolved_path}"
                    )
                    continue
            except OSError:
                log_for_debugging(
                    "[Sandbox Linux] Skipping write path that could not be "
                    f"resolved: {normalized_path}"
                )
                continue

            args.append("--bind")
            args.append(normalized_path)
            args.append(normalized_path)
            allowed_write_paths.append(normalized_path)

        deny_paths: list[str] = [
            *(write_config.get("denyWithinAllow") or []),
            *(
                await linux_get_mandatory_deny_paths(
                    cwd,
                    ripgrep_config,
                    mandatory_deny_search_depth,
                    allow_git_config,
                    abort_signal,
                )
            ),
        ]

        seen_deny_write: set[str] = set()
        for path_pattern in deny_paths:
            raw_path = normalize_path_for_sandbox(path_pattern)
            if raw_path.startswith("/dev/"):
                continue

            normalized_path = resolve_symlinked_deny_path(raw_path)
            if normalized_path is None:
                unresolvable_symlink = find_symlink_in_path(
                    raw_path, allowed_write_paths
                )
                if unresolvable_symlink and unresolvable_symlink not in seen_deny_write:
                    seen_deny_write.add(unresolvable_symlink)
                    deny_write_args.extend(["--ro-bind", "/dev/null", unresolvable_symlink])
                    deny_write_raw_dests[unresolvable_symlink] = raw_path
                log_for_debugging(
                    "[Sandbox Linux] Deny path could not be resolved through "
                    f"symlinks, failing closed: {raw_path}"
                )
                continue
            if normalized_path != raw_path:
                log_for_debugging(
                    "[Sandbox Linux] Resolved symlinked deny path: "
                    f"{raw_path} -> {normalized_path}"
                )
            if normalized_path.startswith("/dev/"):
                continue
            if normalized_path in seen_deny_write:
                continue
            seen_deny_write.add(normalized_path)

            symlink_in_path = find_symlink_in_path(
                normalized_path, allowed_write_paths
            )
            if symlink_in_path:
                if symlink_in_path not in seen_deny_write:
                    seen_deny_write.add(symlink_in_path)
                    deny_write_args.extend(["--ro-bind", "/dev/null", symlink_in_path])
                    deny_write_raw_dests[symlink_in_path] = raw_path
                log_for_debugging(
                    "[Sandbox Linux] Mounted /dev/null at symlink "
                    f"{symlink_in_path} to prevent symlink replacement attack"
                )
                continue

            if not os.path.exists(normalized_path):
                if has_file_ancestor(normalized_path):
                    log_for_debugging(
                        "[Sandbox Linux] Skipping deny path with file ancestor "
                        f"(cannot create paths under a file): {normalized_path}"
                    )
                    continue

                ancestor_path = os.path.dirname(normalized_path)
                while ancestor_path != "/" and not os.path.exists(ancestor_path):
                    ancestor_path = os.path.dirname(ancestor_path)

                ancestor_is_within = any(
                    ancestor_path.startswith(allowed + "/")
                    or ancestor_path == allowed
                    or normalized_path.startswith(allowed + "/")
                    for allowed in allowed_write_paths
                )
                if ancestor_is_within:
                    first_nonexistent = find_first_nonexistent_component(
                        normalized_path
                    )
                    if first_nonexistent != normalized_path:
                        empty_dir = tempfile.mkdtemp(prefix="claude-empty-")
                        deny_write_args.extend(["--ro-bind", empty_dir, first_nonexistent])
                        deny_write_raw_dests[first_nonexistent] = raw_path
                        _BWRAP_MOUNT_POINTS.add(first_nonexistent)
                        _register_exit_cleanup_handler()
                        log_for_debugging(
                            "[Sandbox Linux] Mounted empty dir at "
                            f"{first_nonexistent} to block creation of {normalized_path}"
                        )
                    else:
                        deny_write_args.extend(["--ro-bind", "/dev/null", first_nonexistent])
                        deny_write_raw_dests[first_nonexistent] = raw_path
                        _BWRAP_MOUNT_POINTS.add(first_nonexistent)
                        _register_exit_cleanup_handler()
                        log_for_debugging(
                            "[Sandbox Linux] Mounted /dev/null at "
                            f"{first_nonexistent} to block creation of {normalized_path}"
                        )
                else:
                    log_for_debugging(
                        "[Sandbox Linux] Skipping non-existent deny path not "
                        f"within allowed paths: {normalized_path}"
                    )
                continue

            is_within_allowed = any(
                normalized_path.startswith(allowed + "/")
                or normalized_path == allowed
                for allowed in allowed_write_paths
            )
            if is_within_allowed:
                deny_write_args.extend(["--ro-bind", normalized_path, normalized_path])
                deny_write_raw_dests[normalized_path] = raw_path
            else:
                log_for_debugging(
                    "[Sandbox Linux] Skipping deny path not within allowed "
                    f"paths: {normalized_path}"
                )
    else:
        args.append("--bind")
        args.append("/")
        args.append("/")

    read_deny_paths: list[str] = []
    read_allow_paths = [
        normalize_path_for_sandbox(p)
        for p in (read_config.get("allowWithinDeny") if read_config else []) or []
    ]
    masked_files: dict[str, str] = {}
    tmpfs_dirs: list[str] = []

    if read_config is not None:
        root_skip = {"proc", "dev", "sys"}
        for p in read_config.get("denyOnly") or []:
            if normalize_path_for_sandbox(p) == "/":
                try:
                    children = os.listdir("/")
                except OSError:
                    children = []
                for child in children:
                    if child not in root_skip:
                        read_deny_paths.append("/" + child)
            else:
                read_deny_paths.append(p)

        if os.path.exists("/etc/ssh/ssh_config.d"):
            read_deny_paths.append("/etc/ssh/ssh_config.d")

        normalized_deny_paths = sorted(
            (
                normalize_path_for_sandbox(p)
                for p in read_deny_paths
            ),
            key=lambda p: p.count("/"),
        )

        for normalized_path in normalized_deny_paths:
            if not os.path.exists(normalized_path):
                log_for_debugging(
                    "[Sandbox Linux] Skipping non-existent read deny path: "
                    f"{normalized_path}"
                )
                continue
            if os.path.isdir(normalized_path):
                tmpfs_dirs.append(normalized_path)
                _push_read_deny_dir_mounts(
                    args, normalized_path, allowed_write_paths, read_allow_paths
                )
            else:
                if normalized_path in read_allow_paths:
                    log_for_debugging(
                        "[Sandbox Linux] Skipping read deny for re-allowed "
                        f"path: {normalized_path}"
                    )
                    continue
                deny_dest = resolve_symlink_deny_dest(normalized_path)
                args.append("--ro-bind")
                args.append("/dev/null")
                args.append(deny_dest)
                masked_files[deny_dest] = "/dev/null"
                masked_files[normalized_path] = "/dev/null"

    for bind in masked_file_binds or []:
        dest = resolve_symlink_deny_dest(bind["realPath"])
        args.append("--ro-bind")
        args.append(bind["fakePath"])
        args.append(dest)
        masked_files[dest] = bind["fakePath"]
        masked_files[bind["realPath"]] = bind["fakePath"]

    def is_hidden_by_tmpfs(dest: str) -> bool:
        for tmpfs_dir in tmpfs_dirs:
            under_tmpfs = dest == tmpfs_dir or dest.startswith(tmpfs_dir + "/")
            if not under_tmpfs:
                continue
            re_exposed = any(
                (write_path == tmpfs_dir or write_path.startswith(tmpfs_dir + "/"))
                and (dest == write_path or dest.startswith(write_path + "/"))
                for write_path in allowed_write_paths
            )
            if not re_exposed:
                return True
        return False

    emitted_deny_write_dests: list[str] = []
    for i in range(0, len(deny_write_args), 3):
        dest = deny_write_args[i + 2]
        raw_dest = deny_write_raw_dests.get(dest, dest)
        if dest in masked_files:
            continue
        if is_hidden_by_tmpfs(dest) or is_hidden_by_tmpfs(raw_dest):
            log_for_debugging(
                "[Sandbox Linux] Skipping denyWrite bind already hidden by "
                f"denyRead tmpfs: {dest}"
            )
            continue
        args.extend([deny_write_args[i], deny_write_args[i + 1], dest])
        emitted_deny_write_dests.append(dest)
        if raw_dest != dest:
            emitted_deny_write_dests.append(raw_dest)

    for tmpfs_dir in tmpfs_dirs:
        if any(tmpfs_dir == dest or tmpfs_dir.startswith(dest + "/") for dest in emitted_deny_write_dests):
            log_for_debugging(
                "[Sandbox Linux] Re-applying denyRead tmpfs re-exposed by "
                f"denyWrite bind: {tmpfs_dir}"
            )
            _push_read_deny_dir_mounts(
                args, tmpfs_dir, allowed_write_paths, read_allow_paths
            )

    for masked_file, source in masked_files.items():
        if any(masked_file.startswith(dest + "/") for dest in emitted_deny_write_dests):
            if resolve_symlink_deny_dest(masked_file) != masked_file:
                continue
            log_for_debugging(
                "[Sandbox Linux] Re-applying file mask re-exposed by "
                f"denyWrite bind: {masked_file}"
            )
            args.append("--ro-bind")
            args.append(source)
            args.append(masked_file)

    if masked_file_store_dir is not None:
        args.append("--ro-bind")
        args.append(masked_file_store_dir)
        args.append(masked_file_store_dir)

    return args


async def wrap_command_with_sandbox_linux(
    *,
    command: str,
    needs_network_restriction: bool,
    http_socket_path: str | None = None,
    socks_socket_path: str | None = None,
    http_proxy_port: int | None = None,
    socks_proxy_port: int | None = None,
    proxy_auth_token: str | None = None,
    ca_cert_path: str | None = None,
    read_config: FsReadRestrictionConfig | None = None,
    write_config: FsWriteRestrictionConfig | None = None,
    unset_env_vars: list[str] | None = None,
    set_env_vars: dict[str, str] | None = None,
    masked_file_binds: list[dict[str, str]] | None = None,
    masked_file_store_dir: str | None = None,
    enable_weaker_nested_sandbox: bool = False,
    allow_all_unix_sockets: bool = False,
    bin_shell: str | None = None,
    ripgrep_config: dict[str, Any] | None = None,
    mandatory_deny_search_depth: int = DEFAULT_MANDATORY_DENY_SEARCH_DEPTH,
    allow_git_config: bool = False,
    git_safe_directories: list[str] | None = None,
    seccomp_config: dict[str, Any] | None = None,
    bwrap_path: str | None = None,
    socat_path: str | None = None,
    observe_socket_path: str | None = None,
    abort_signal: asyncio.Future | None = None,
    cwd: str | None = None,
    preserve_fds: list[int] | None = None,
) -> list[str]:
    """Build the bwrap argv for one sandboxed command.

    ADAPT: returns ``[bwrap, ...args, '--', shell, '-c', script]`` for a
    direct spawn (upstream returns a shell string). ``enableWeakerNestedSandbox``
    and ``allowAllUnixSockets`` are always false in production (config
    validation rejects them) but kept as parameters for parity; passing True
    raises.
    """
    if enable_weaker_nested_sandbox:
        raise ValueError(
            "enableWeakerNestedSandbox is not exposed as a production "
            "weakening switch"
        )
    if allow_all_unix_sockets:
        raise ValueError(
            "allowAllUnixSockets is not exposed as a production weakening switch"
        )

    has_read_restrictions = (read_config and len(read_config.get("denyOnly") or []) > 0) or bool(
        masked_file_binds
    )
    has_write_restrictions = write_config is not None
    has_env_restrictions = bool(unset_env_vars) or bool(set_env_vars)
    has_git_config = bool(git_safe_directories)
    preserved_descriptors = list(preserve_fds or [])
    for descriptor in preserved_descriptors:
        if descriptor <= 2:
            raise ValueError("preserved sandbox descriptor must be greater than stderr")

    if (
        not needs_network_restriction
        and not has_read_restrictions
        and not has_write_restrictions
        and not has_env_restrictions
        and not has_git_config
        and not preserved_descriptors
    ):
        return ["bash", "-c", command]

    global _active_sandbox_count
    _active_sandbox_count += 1

    bwrap_args: list[str] = ["--new-session", "--die-with-parent"]
    for descriptor in preserved_descriptors:
        bwrap_args.extend(["--preserve-fds", str(descriptor)])
    apply_seccomp_prefix: str | None = None

    try:
        if not allow_all_unix_sockets:
            apply_seccomp_prefix = resolve_apply_seccomp_prefix(
                (seccomp_config or {}).get("applyPath"),
                (seccomp_config or {}).get("argv0"),
            )
            if apply_seccomp_prefix is None:
                log_for_debugging(
                    "[Sandbox Linux] apply-seccomp binary not available - "
                    "unix socket blocking disabled. Install the vendored "
                    "helper for full protection.",
                    level="warn",
                )
            else:
                log_for_debugging(
                    "[Sandbox Linux] Applying seccomp filter for Unix socket "
                    "blocking"
                )
        else:
            log_for_debugging(
                "[Sandbox Linux] Skipping seccomp filter - allowAllUnixSockets "
                "is enabled"
            )

        if observe_socket_path and apply_seccomp_prefix:
            if os.path.exists(observe_socket_path):
                bwrap_args.append("--bind")
                bwrap_args.append(observe_socket_path)
                bwrap_args.append(observe_socket_path)
                bwrap_args.append("--setenv")
                bwrap_args.append("SRT_OBSERVE_SOCK")
                bwrap_args.append(observe_socket_path)
                bwrap_args.append("--setenv")
                bwrap_args.append("SRT_ENCODED_CMD")
                bwrap_args.append(encode_sandboxed_command(command))
            else:
                log_for_debugging(
                    "[Sandbox Linux] observe socket missing — supervisor not "
                    "running; continuing without violation monitoring"
                )

        if has_env_restrictions:
            for name in unset_env_vars or []:
                bwrap_args.append("--unsetenv")
                bwrap_args.append(name)
            for name, value in (set_env_vars or {}).items():
                bwrap_args.append("--setenv")
                bwrap_args.append(name)
                bwrap_args.append(value)

        if git_safe_directories:
            git_cfg = build_posix_git_safe_dir_env(
                git_safe_directories, unset_env_vars, set_env_vars
            )
            for name, value in git_cfg.items():
                bwrap_args.append("--setenv")
                bwrap_args.append(name)
                bwrap_args.append(value)

        if needs_network_restriction:
            bwrap_args.append("--unshare-net")
            if http_socket_path and socks_socket_path:
                if not os.path.exists(http_socket_path):
                    raise RuntimeError(
                        f"Linux HTTP bridge socket does not exist: "
                        f"{http_socket_path}. The bridge process may have "
                        "died. Try reinitializing the sandbox."
                    )
                if not os.path.exists(socks_socket_path):
                    raise RuntimeError(
                        f"Linux SOCKS bridge socket does not exist: "
                        f"{socks_socket_path}. The bridge process may have "
                        "died. Try reinitializing the sandbox."
                    )
                bwrap_args.append("--bind")
                bwrap_args.append(http_socket_path)
                bwrap_args.append(http_socket_path)
                if socks_socket_path != http_socket_path:
                    bwrap_args.append("--bind")
                    bwrap_args.append(socks_socket_path)
                    bwrap_args.append(socks_socket_path)

                proxy_env = generate_proxy_env_vars(
                    3128,
                    1080,
                    ca_cert_path,
                    proxy_auth_token,
                    write_config is None,
                )
                for env in proxy_env:
                    first_eq = env.index("=")
                    bwrap_args.append("--setenv")
                    bwrap_args.append(env[:first_eq])
                    bwrap_args.append(env[first_eq + 1 :])

                if http_proxy_port is not None:
                    bwrap_args.append("--setenv")
                    bwrap_args.append("CLAUDE_CODE_HOST_HTTP_PROXY_PORT")
                    bwrap_args.append(str(http_proxy_port))
                if socks_proxy_port is not None:
                    bwrap_args.append("--setenv")
                    bwrap_args.append("CLAUDE_CODE_HOST_SOCKS_PROXY_PORT")
                    bwrap_args.append(str(socks_proxy_port))

        fs_args = await generate_filesystem_args(
            read_config,
            write_config,
            masked_file_binds,
            masked_file_store_dir,
            ripgrep_config,
            mandatory_deny_search_depth,
            allow_git_config,
            abort_signal,
            cwd,
        )
        bwrap_args.extend(fs_args)

        bwrap_args.append("--dev")
        bwrap_args.append("/dev")

        bwrap_args.append("--unshare-pid")
        if not enable_weaker_nested_sandbox:
            bwrap_args.append("--unshare-user")
            bwrap_args.append("--cap-drop")
            bwrap_args.append("ALL")
            bwrap_args.append("--proc")
            bwrap_args.append("/proc")
        else:
            bwrap_args.append("--unshare-user")
            bwrap_args.append("--bind")
            bwrap_args.append("/proc")
            bwrap_args.append("/proc")

        shell_name = bin_shell or "bash"
        shell = which(shell_name)
        if not shell:
            raise RuntimeError(f"Shell '{shell_name}' not found in PATH")
        bwrap_args.append("--")
        bwrap_args.append(shell)
        bwrap_args.append("-c")

        if needs_network_restriction and http_socket_path and socks_socket_path:
            sandbox_command = build_sandbox_command(
                http_socket_path,
                socks_socket_path,
                command,
                apply_seccomp_prefix,
                shell,
                socat_path,
            )
            bwrap_args.append(sandbox_command)
        elif apply_seccomp_prefix:
            apply_seccomp_cmd = apply_seccomp_prefix + shell_quote(
                [shell, "-c", command]
            )
            bwrap_args.append(apply_seccomp_cmd)
        else:
            bwrap_args.append(command)

        restrictions: list[str] = []
        if needs_network_restriction:
            restrictions.append("network")
        if has_read_restrictions or has_write_restrictions:
            restrictions.append("filesystem")
        if has_env_restrictions:
            restrictions.append("env")
        if apply_seccomp_prefix:
            restrictions.append("seccomp(unix-block)")
        log_for_debugging(
            "[Sandbox Linux] Wrapped command with bwrap "
            f"({', '.join(restrictions)} restrictions)"
        )

        bwrap = bwrap_path or "bwrap"
        return [bwrap, *bwrap_args]
    except Exception:
        if _active_sandbox_count > 0:
            _active_sandbox_count -= 1
        raise


# ---------------------------------------------------------------------------
# linux-violation-monitor.ts — filesystem socket observer
# ---------------------------------------------------------------------------

class LinuxViolationMonitor:
    """Unix-socket listener fed by apply-seccomp USER_NOTIF observations.

    Each apply-seccomp instance connects and streams newline-JSON events;
    the monitor intersects each absolute path against the allow/deny write
    set before forwarding as a violation (kernel reports attempts, not
    denials). Events are diagnostic hints — bwrap's mount table is the only
    enforcement boundary.
    """

    def __init__(
        self,
        callback: SandboxViolationCallback,
        *,
        allow_write_paths: list[str],
        deny_write_paths: list[str],
        ignore_violations: dict[str, list[str]] | None = None,
    ) -> None:
        self._callback = callback
        self._allow_write_paths = allow_write_paths
        self._deny_write_paths = deny_write_paths
        self._ignore_violations = ignore_violations or {}
        self._wildcard_paths = self._ignore_violations.get("*") or []
        self._command_patterns = [
            (k, v)
            for k, v in self._ignore_violations.items()
            if k != "*"
        ]
        self._sock_dir: str | None = None
        self._sock_path: str | None = None
        self._server: asyncio.base_events.Server | None = None
        self._connections: set[asyncio.StreamReader] = set()
        self.observe_socket_path: str | None = None
        self._ready: asyncio.Future[None] | None = None
        self._stopped = False

    @property
    def ready(self) -> asyncio.Future[None]:
        if self._ready is None:
            self._ready = asyncio.get_event_loop().create_future()
        return self._ready

    async def start(self) -> None:
        sock_dir = tempfile.mkdtemp(prefix="srt-obs-")
        self._sock_dir = sock_dir
        sock_path = os.path.join(sock_dir, f"s{os.urandom(4).hex()}.sock")
        self._sock_path = sock_path

        def _under_prefix(p: str, prefix: str) -> bool:
            return p == prefix or p.startswith(
                prefix if prefix.endswith("/") else prefix + "/"
            )

        def _is_denied(p: str) -> bool:
            norm = os.path.normpath(p)
            if any(_under_prefix(norm, d) for d in self._deny_write_paths):
                return True
            return not any(
                _under_prefix(norm, a) for a in self._allow_write_paths
            )

        def _should_ignore(path: str, command: str | None) -> bool:
            if any(w in path for w in self._wildcard_paths):
                return True
            if command:
                for pattern, paths in self._command_patterns:
                    if pattern in command and any(w in path for w in paths):
                        return True
            return False

        def _handle_event(event: dict[str, Any], encoded_command: str | None) -> None:
            if event.get("observe_init_error"):
                log_for_debugging(
                    "[Sandbox Linux Monitor] observe filter not installed: "
                    f"{event['observe_init_error']}"
                )
                return
            path = event.get("path")
            if not isinstance(path, str):
                return
            if not path.startswith("/"):
                return
            if not _is_denied(path):
                return
            command: str | None = None
            if encoded_command:
                try:
                    command = decode_sandboxed_command(encoded_command)
                except Exception:
                    pass
            if _should_ignore(path, command):
                return
            self._callback(
                SandboxViolationEvent(
                    line=f"deny {event.get('syscall', 'syscall')} {path}",
                    command=command,
                    encodedCommand=encoded_command,
                    timestamp=None,
                )
            )

        async def _handle_client(
            reader: asyncio.StreamReader, _writer: asyncio.StreamWriter
        ) -> None:
            self._connections.add(reader)
            encoded_command: str | None = None
            try:
                while True:
                    raw = await reader.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(event, dict):
                        ev_encoded = event.get("encodedCommand")
                        if isinstance(ev_encoded, str) and encoded_command is None:
                            encoded_command = ev_encoded
                        _handle_event(event, encoded_command or ev_encoded)
                    else:
                        continue
            except (asyncio.IncompleteReadError, ConnectionError, OSError):
                pass
            finally:
                self._connections.discard(reader)

        loop = asyncio.get_event_loop()

        def _on_server_error(exc: Exception) -> None:
            log_for_debugging(
                "[Sandbox Linux Monitor] listen failed: "
                f"{exc} - violation monitoring disabled",
                level="warn",
            )
            self.observe_socket_path = None
            if not self.ready.done():
                self.ready.set_result(None)

        try:
            server = await asyncio.start_unix_server(
                _handle_client, path=sock_path
            )
        except OSError as exc:
            _on_server_error(exc)
            return
        self._server = server
        self.observe_socket_path = sock_path
        if not self.ready.done():
            self.ready.set_result(None)
        log_for_debugging(
            f"[Sandbox Linux Monitor] listening on {sock_path}"
        )

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        log_for_debugging("[Sandbox Linux Monitor] stopping")
        if self._server is not None:
            self._server.close()
        if self._sock_dir is not None:
            shutil.rmtree(self._sock_dir, ignore_errors=True)


def start_linux_sandbox_violation_monitor(
    callback: SandboxViolationCallback,
    opts: dict[str, Any],
) -> LinuxViolationMonitor:
    """Sync factory matching the upstream signature; callers await
    ``await monitor.start()`` before use (ready future mirrors the
    upstream listen callback)."""
    monitor = LinuxViolationMonitor(
        callback,
        allow_write_paths=opts["allowWritePaths"],
        deny_write_paths=opts["denyWritePaths"],
        ignore_violations=opts.get("ignoreViolations"),
    )
    return monitor
