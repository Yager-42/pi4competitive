"""SRT sandbox manager — session-level state, network proxy lifecycle,
platform dispatch for wrap, violation store, and reset.

Source: sandbox-runtime@0.0.67 ``src/sandbox/{sandbox-manager,sandbox-violation-store}.ts``
Repository: anthropics/sandbox-runtime @ 21d8f75e1bc00eede09b3103e68b2eae097110d1
License: Apache-2.0 (retained under the native sandbox license directory)

Host delta (ADAPT, per G0 map §4.1): a narrow manager without the unused
optional imports (credentials/TLS/MITM/Windows). ``wrapWithSandbox`` returns
an argv list instead of a shell string (``wrapWithSandboxArgv`` merges into
it: the Python spawn contract is always argv + the host env). The violation
store is folded into this module (the target layout has no separate file).
The ask callback is an optional ``(host, port) -> bool`` coroutine; with
``strictAllowlist`` or no callback, unmatched hosts are denied (network
default deny). Proxy auth token, mux, and Linux bridge lifetimes mirror
upstream exactly. ``unref`` semantics are irrelevant to asyncio and
omitted.
"""
from __future__ import annotations

import asyncio
import copy
import os
import secrets
from typing import Any, Awaitable, Callable

from .linux import (
    LinuxNetworkBridgeContext,
    cleanup_bwrap_mount_points,
    check_linux_dependencies,
    initialize_linux_network_bridge,
    start_linux_sandbox_violation_monitor,
    stop_linux_network_bridge,
    wrap_command_with_sandbox_linux,
)
from .macos import (
    SandboxViolationCallback,
    SandboxViolationEvent,
    start_macos_sandbox_log_monitor,
    wrap_command_with_sandbox_macos,
)
from .policy import (
    CredentialRestrictionConfig,
    FsReadRestrictionConfig,
    FsWriteRestrictionConfig,
    NetworkRestrictionConfig,
    SandboxRuntimeConfig,
    contains_glob_chars,
    deep_clone_config,
    empty_credential_restrictions,
    encode_sandboxed_command,
    expand_glob_pattern,
    get_default_write_paths,
    linux_glob_pattern_warning_paths,
    matches_domain_pattern,
    remove_trailing_glob_suffix,
)
from .process import get_platform, log_for_debugging
from .proxy import (
    HttpProxyServer,
    MuxProxyServer,
    ResolvedParentProxy,
    SocksProxyServer,
    canonicalize_host,
    is_valid_host,
    redact_url,
    resolve_parent_proxy,
)
from .seccomp import get_apply_seccomp_binary_path

SandboxAskCallback = Callable[[dict[str, Any]], Awaitable[bool] | bool]

# ---------------------------------------------------------------------------
# Violation store (sandbox-violation-store.ts, folded per G0 map §4.1)
# ---------------------------------------------------------------------------

class SandboxViolationStore:
    """In-memory tail (100) of sandbox violations; total count kept."""

    def __init__(self) -> None:
        self._violations: list[SandboxViolationEvent] = []
        self._total_count = 0
        self._max_size = 100
        self._listeners: set[
            Callable[[list[SandboxViolationEvent]], None]
        ] = set()

    def add_violation(self, violation: SandboxViolationEvent) -> None:
        self._violations.append(violation)
        self._total_count += 1
        if len(self._violations) > self._max_size:
            self._violations = self._violations[-self._max_size :]
        self._notify_listeners()

    def get_violations(
        self, limit: int | None = None
    ) -> list[SandboxViolationEvent]:
        if limit is None:
            return list(self._violations)
        return self._violations[-limit:]

    def get_count(self) -> int:
        return len(self._violations)

    def get_total_count(self) -> int:
        return self._total_count

    def get_violations_for_command(
        self, command: str
    ) -> list[SandboxViolationEvent]:
        command_base64 = encode_sandboxed_command(command)
        return [
            v for v in self._violations if v.encodedCommand == command_base64
        ]

    def clear(self) -> None:
        self._violations = []
        # Total count is intentionally kept when clearing.
        self._notify_listeners()

    def subscribe(
        self, listener: Callable[[list[SandboxViolationEvent]], None]
    ) -> Callable[[], None]:
        self._listeners.add(listener)
        listener(self.get_violations())
        return lambda: self._listeners.discard(listener)

    def _notify_listeners(self) -> None:
        violations = self.get_violations()
        for listener in list(self._listeners):
            listener(violations)


# ---------------------------------------------------------------------------
# Module state (private, like upstream)
# ---------------------------------------------------------------------------

_config: SandboxRuntimeConfig | None = None
_http_proxy_server: HttpProxyServer | None = None
_socks_proxy_server: SocksProxyServer | None = None
_mux_proxy_server: MuxProxyServer | None = None
_manager_context: dict[str, Any] | None = None
_initialization_lock: asyncio.Lock | None = None
_initialization_done: asyncio.Event | None = None
_initialization_error: Exception | None = None
_log_monitor_shutdown: Callable[[], None] | None = None
_linux_monitor: Any = None
_parent_proxy: ResolvedParentProxy | None = None
_proxy_auth_token: str | None = None
_sandbox_violation_store = SandboxViolationStore()


# ---------------------------------------------------------------------------
# Network filtering (filterNetworkRequest)
# ---------------------------------------------------------------------------

async def filter_network_request(
    port: int,
    host: str,
    sandbox_ask_callback: SandboxAskCallback | None = None,
) -> bool:
    if _config is None:
        log_for_debugging("No config available, denying network request")
        return False

    if not is_valid_host(host):
        log_for_debugging(
            f"Denying malformed host: {host!r}:{port}", level="error"
        )
        return False

    canonical_host = canonicalize_host(host) or host

    for denied_domain in _config["network"].get("deniedDomains") or []:
        if matches_domain_pattern(canonical_host, denied_domain):
            log_for_debugging(f"Denied by config rule: {host}:{port}")
            return False

    for allowed_domain in _config["network"].get("allowedDomains") or []:
        if matches_domain_pattern(canonical_host, allowed_domain):
            log_for_debugging(f"Allowed by config rule: {host}:{port}")
            return True

    if not sandbox_ask_callback or _config["network"].get("strictAllowlist"):
        log_for_debugging(f"No matching config rule, denying: {host}:{port}")
        return False

    log_for_debugging(f"No matching config rule, asking user: {host}:{port}")
    try:
        result = sandbox_ask_callback({"host": host, "port": port})
        if asyncio.iscoroutine(result):
            user_allowed = bool(await result)
        else:
            user_allowed = bool(result)
        if user_allowed:
            log_for_debugging(f"User allowed: {host}:{port}")
            return True
        log_for_debugging(f"User denied: {host}:{port}")
        return False
    except Exception as error:  # noqa: BLE001 — upstream logs and denies
        log_for_debugging(f"Error in permission callback: {error}", level="error")
        return False


# ---------------------------------------------------------------------------
# Proxy lifecycle (startMuxProxyServer)
# ---------------------------------------------------------------------------

async def start_mux_proxy_server(
    sandbox_ask_callback: SandboxAskCallback | None,
) -> int:
    global _http_proxy_server, _socks_proxy_server, _mux_proxy_server

    _http_proxy_server = HttpProxyServer(
        lambda port, host: filter_network_request(port, host, sandbox_ask_callback),
        proxy_auth_token=_proxy_auth_token,
        parent_proxy=_parent_proxy,
    )
    _socks_proxy_server = SocksProxyServer(
        lambda port, host: filter_network_request(port, host, sandbox_ask_callback),
        proxy_auth_token=_proxy_auth_token,
        parent_proxy=_parent_proxy,
    )
    _mux_proxy_server = MuxProxyServer(
        http_backend=_http_proxy_server,
        handle_socks=_socks_proxy_server.handle_connection,
    )
    await _mux_proxy_server.listen_http_backend()
    await _mux_proxy_server.listen("127.0.0.1", 0)
    mux_port = _mux_proxy_server.get_port()
    if mux_port is None:
        raise RuntimeError("Failed to get mux proxy server port")
    log_for_debugging(f"Mux proxy (HTTP+SOCKS) listening on localhost:{mux_port}")
    return mux_port


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------

def is_supported_platform() -> bool:
    platform = get_platform()
    if platform == "linux":
        from .process import get_wsl_version

        return get_wsl_version() != "1"
    return platform == "macos"


def is_sandboxing_enabled() -> bool:
    return _config is not None


def check_dependencies(
    ripgrep_config: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    if not is_supported_platform():
        return {"errors": ["Unsupported platform"], "warnings": []}
    errors: list[str] = []
    warnings: list[str] = []
    platform = get_platform()
    if platform == "linux":
        rg = ripgrep_config or (_config or {}).get("ripgrep") or {"command": "rg"}
        from .process import which

        if which(rg.get("command", "rg")) is None:
            errors.append(f"ripgrep ({rg.get('command', 'rg')}) not found")
        linux_deps = check_linux_dependencies(
            seccomp_config=(_config or {}).get("seccomp"),
            bwrap_path=(_config or {}).get("bwrapPath"),
            socat_path=(_config or {}).get("socatPath"),
        )
        errors.extend(linux_deps["errors"])
        warnings.extend(linux_deps["warnings"])
    return {"errors": errors, "warnings": warnings}


async def check_dependencies_async(
    ripgrep_config: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    return check_dependencies(ripgrep_config)


async def initialize(
    runtime_config: SandboxRuntimeConfig,
    sandbox_ask_callback: SandboxAskCallback | None = None,
    enable_log_monitor: bool = False,
) -> None:
    """Initialize the sandbox session: dependency checks, violation
    monitors, and the mux proxy + Linux bridge. Idempotent while an
    initialization is in flight (upstream promise semantics)."""
    global _config, _parent_proxy, _proxy_auth_token, _manager_context
    global _log_monitor_shutdown, _linux_monitor, _initialization_lock
    global _initialization_done, _initialization_error

    if _initialization_lock is None:
        _initialization_lock = asyncio.Lock()
        _initialization_done = asyncio.Event()
    if _initialization_done.is_set() or _manager_context is not None:
        if _initialization_error is not None:
            raise _initialization_error
        return

    async with _initialization_lock:
        if _manager_context is not None or _initialization_done.is_set():
            if _initialization_error is not None:
                raise _initialization_error
            return

        _initialization_error = None
        _config = deep_clone_config(runtime_config)
        _parent_proxy = resolve_parent_proxy(
            runtime_config.get("network", {}).get("parentProxy")
        )
        if _parent_proxy:
            log_for_debugging(
                f"Parent proxy configured: http={redact_url(_parent_proxy.http_url)} "
                f"https={redact_url(_parent_proxy.https_url)}"
            )

        deps = await check_dependencies_async()
        if deps["errors"]:
            _config = None
            raise RuntimeError(
                f"Sandbox dependencies not available: {', '.join(deps['errors'])}"
            )

        try:
            if enable_log_monitor and get_platform() == "macos":
                _log_monitor_shutdown = start_macos_sandbox_log_monitor(
                    _sandbox_violation_store.add_violation,
                    (_config or {}).get("ignoreViolations"),
                )
                log_for_debugging("Started macOS sandbox log monitor")
            if enable_log_monitor and get_platform() == "linux":
                monitor = start_linux_sandbox_violation_monitor(
                    _sandbox_violation_store.add_violation,
                    {
                        "allowWritePaths": [
                            *get_default_write_paths(),
                            *(_config or {}).get("filesystem", {}).get(
                                "allowWrite", []
                            ),
                        ],
                        "denyWritePaths": (_config or {}).get(
                            "filesystem", {}
                        ).get("denyWrite", []),
                        "ignoreViolations": (_config or {}).get(
                            "ignoreViolations"
                        ),
                    },
                )
                _linux_monitor = monitor
                await monitor.start()
                log_for_debugging("Started Linux seccomp violation monitor")

            _proxy_auth_token = secrets.token_hex(16)
            network = (_config or {}).get("network") or {}
            need_local_proxy = (
                network.get("httpProxyPort") is None
                or network.get("socksProxyPort") is None
            )
            mux_port = (
                await start_mux_proxy_server(sandbox_ask_callback)
                if need_local_proxy
                else None
            )
            http_proxy_port = network.get("httpProxyPort") or mux_port
            socks_proxy_port = network.get("socksProxyPort") or mux_port

            linux_bridge: LinuxNetworkBridgeContext | None = None
            if get_platform() == "linux":
                linux_bridge = await initialize_linux_network_bridge(
                    http_proxy_port or 0,
                    socks_proxy_port or 0,
                    (_config or {}).get("socatPath"),
                )

            _manager_context = {
                "httpProxyPort": http_proxy_port,
                "socksProxyPort": socks_proxy_port,
                "linuxBridge": linux_bridge,
            }
            log_for_debugging("Network infrastructure initialized")
            if _initialization_done is not None:
                _initialization_done.set()
        except Exception as error:
            _initialization_error = error
            _config = None
            _manager_context = None
            await _reset_infra()
            raise


# ---------------------------------------------------------------------------
# Config getters (mirror the upstream accessor set)
# ---------------------------------------------------------------------------

def _get_fs_read_config() -> FsReadRestrictionConfig:
    if not _config or (_config.get("filesystem") or {}).get("disabled"):
        return {"denyOnly": [], "allowWithinDeny": []}

    raw_deny_read = _config["filesystem"].get("denyRead") or []
    deny_paths: list[str] = []
    for p in raw_deny_read:
        stripped = remove_trailing_glob_suffix(p)
        if get_platform() == "linux" and contains_glob_chars(stripped):
            expanded = expand_glob_pattern(p)
            log_for_debugging(
                f'[Sandbox] Expanded glob pattern "{p}" to '
                f"{len(expanded)} paths on Linux"
            )
            deny_paths.extend(expanded)
        else:
            deny_paths.append(stripped)

    allow_paths: list[str] = []
    for p in _config["filesystem"].get("allowRead") or []:
        stripped = remove_trailing_glob_suffix(p)
        if get_platform() == "linux" and contains_glob_chars(stripped):
            expanded = expand_glob_pattern(p)
            log_for_debugging(
                f'[Sandbox] Expanded allowRead glob pattern "{p}" to '
                f"{len(expanded)} paths on Linux"
            )
            allow_paths.extend(expanded)
        else:
            allow_paths.append(stripped)
    return {"denyOnly": deny_paths, "allowWithinDeny": allow_paths}


def _get_fs_write_config() -> FsWriteRestrictionConfig:
    if not _config:
        return {"allowOnly": get_default_write_paths(), "denyWithinAllow": []}
    if (_config.get("filesystem") or {}).get("disabled"):
        return {"allowOnly": ["/"], "denyWithinAllow": []}

    def _strip_globs(paths: list[str]) -> list[str]:
        out: list[str] = []
        for p in paths:
            stripped = remove_trailing_glob_suffix(p)
            if get_platform() == "linux" and contains_glob_chars(stripped):
                log_for_debugging(f"Skipping glob pattern on Linux/WSL: {p}")
                continue
            out.append(stripped)
        return out

    allow_paths = _strip_globs(_config["filesystem"].get("allowWrite") or [])
    deny_paths = _strip_globs(_config["filesystem"].get("denyWrite") or [])
    return {
        "allowOnly": [*get_default_write_paths(), *allow_paths],
        "denyWithinAllow": deny_paths,
    }


def get_network_restriction_config() -> NetworkRestrictionConfig:
    if not _config:
        return {}
    allowed_hosts = _config["network"].get("allowedDomains") or []
    denied_hosts = _config["network"].get("deniedDomains") or []
    result: NetworkRestrictionConfig = {"allowedHosts": allowed_hosts}
    if denied_hosts:
        result["deniedHosts"] = denied_hosts
    return result


def _get_allow_unix_sockets() -> list[str] | None:
    return (_config or {}).get("network", {}).get("allowUnixSockets")


def _get_allow_local_binding() -> bool | None:
    return (_config or {}).get("network", {}).get("allowLocalBinding")


def _get_allow_mach_lookup() -> list[str] | None:
    return (_config or {}).get("network", {}).get("allowMachLookup")


def _get_ignore_violations() -> dict[str, list[str]] | None:
    return (_config or {}).get("ignoreViolations")


def _get_allow_apple_events() -> bool | None:
    return (_config or {}).get("allowAppleEvents")


def _get_ripgrep_config() -> dict[str, Any]:
    return (_config or {}).get("ripgrep") or {"command": "rg"}


def _get_mandatory_deny_search_depth() -> int:
    return (_config or {}).get("mandatoryDenySearchDepth") or 3


def _get_allow_git_config() -> bool:
    return bool((_config or {}).get("filesystem", {}).get("allowGitConfig"))


def _get_git_safe_directories(
    custom_config: SandboxRuntimeConfig | None = None,
) -> list[str]:
    return [
        *((_config or {}).get("git", {}).get("safeDirectories") or []),
        *((custom_config or {}).get("git", {}).get("safeDirectories") or []),
    ]


def _get_seccomp_config() -> dict[str, Any] | None:
    return (_config or {}).get("seccomp")


def get_proxy_auth_token() -> str | None:
    return _proxy_auth_token


def get_proxy_port() -> int | None:
    return (_manager_context or {}).get("httpProxyPort")


def get_socks_proxy_port() -> int | None:
    return (_manager_context or {}).get("socksProxyPort")


def get_linux_http_socket_path() -> str | None:
    bridge = (_manager_context or {}).get("linuxBridge")
    return bridge.http_socket_path if bridge else None


def get_linux_socks_socket_path() -> str | None:
    bridge = (_manager_context or {}).get("linuxBridge")
    return bridge.socks_socket_path if bridge else None


async def wait_for_network_initialization() -> bool:
    if not _config:
        return False
    if _initialization_done is not None and not _initialization_done.is_set():
        await _initialization_done.wait()
    if _initialization_error is not None:
        return False
    return _manager_context is not None


# ---------------------------------------------------------------------------
# wrapWithSandbox (argv form)
# ---------------------------------------------------------------------------

async def wrap_with_sandbox(
    command: str,
    bin_shell: str | None = None,
    custom_config: SandboxRuntimeConfig | None = None,
    abort_signal: asyncio.Future | None = None,
    cwd: str | None = None,
) -> list[str]:
    """Build the argv to spawn one sandboxed command (platform dispatch).
    ADAPT: returns argv; the spawner uses ``shell=False`` with this argv and
    the host environment (bwrap/sandbox-exec receive their env via
    ``--setenv``/``env`` args, so no env mapping is returned)."""
    platform = get_platform()
    if platform not in ("linux", "macos"):
        raise RuntimeError(
            f"Sandbox configuration is not supported on platform: {platform}"
        )

    fs_custom = custom_config.get("filesystem") if custom_config else None
    fs_disabled = (
        fs_custom.get("disabled", False)
        if fs_custom is not None
        else bool((_config or {}).get("filesystem", {}).get("disabled"))
    )

    credential_restrictions: CredentialRestrictionConfig = (
        empty_credential_restrictions()
    )

    write_config: FsWriteRestrictionConfig | None = None
    read_config: FsReadRestrictionConfig | None = None
    if not fs_disabled:
        def _strip_globs(paths: list[str]) -> list[str]:
            out: list[str] = []
            for p in paths:
                stripped = remove_trailing_glob_suffix(p)
                if platform == "linux" and contains_glob_chars(stripped):
                    log_for_debugging(
                        f"[Sandbox] Skipping glob write pattern on Linux: {p}"
                    )
                    continue
                out.append(stripped)
            return out

        user_allow_write = _strip_globs(
            (fs_custom or {}).get("allowWrite") or []
            if fs_custom is not None
            else (_config or {}).get("filesystem", {}).get("allowWrite") or []
        )
        write_config = {
            "allowOnly": [*get_default_write_paths(), *user_allow_write],
            "denyWithinAllow": _strip_globs(
                (fs_custom or {}).get("denyWrite") or []
                if fs_custom is not None
                else (_config or {}).get("filesystem", {}).get("denyWrite") or []
            ),
        }

        raw_deny_read = (
            (fs_custom or {}).get("denyRead") or []
            if fs_custom is not None
            else (_config or {}).get("filesystem", {}).get("denyRead") or []
        )
        expanded_deny_read: list[str] = []
        for p in raw_deny_read:
            stripped = remove_trailing_glob_suffix(p)
            if platform == "linux" and contains_glob_chars(stripped):
                expanded_deny_read.extend(expand_glob_pattern(p))
            else:
                expanded_deny_read.append(stripped)
        raw_allow_read = (
            (fs_custom or {}).get("allowRead") or []
            if fs_custom is not None
            else (_config or {}).get("filesystem", {}).get("allowRead") or []
        )
        expanded_allow_read: list[str] = []
        for p in raw_allow_read:
            stripped = remove_trailing_glob_suffix(p)
            if platform == "linux" and contains_glob_chars(stripped):
                expanded_allow_read.extend(expand_glob_pattern(p))
            else:
                expanded_allow_read.append(stripped)
        read_config = {
            "denyOnly": expanded_deny_read,
            "allowWithinDeny": expanded_allow_read,
        }

    network_custom = custom_config.get("network") if custom_config else None
    has_network_config = (
        network_custom.get("allowedDomains") is not None
        if network_custom is not None
        else (_config or {}).get("network", {}).get("allowedDomains") is not None
    )
    needs_network_restriction = bool(has_network_config)
    needs_network_proxy = bool(has_network_config)

    if needs_network_proxy:
        await wait_for_network_initialization()

    allow_pty = (
        (custom_config or {}).get("allowPty")
        if custom_config is not None
        else (_config or {}).get("allowPty")
    )
    git_safe_directories = _get_git_safe_directories(custom_config)

    if platform == "macos":
        return await _wrap_macos(
            command=command,
            needs_network_restriction=needs_network_restriction,
            needs_network_proxy=needs_network_proxy,
            read_config=read_config,
            write_config=write_config,
            credential_restrictions=credential_restrictions,
            allow_pty=bool(allow_pty),
            git_safe_directories=git_safe_directories,
            bin_shell=bin_shell,
        )
    return await _wrap_linux(
        command=command,
        needs_network_restriction=needs_network_restriction,
        needs_network_proxy=needs_network_proxy,
        read_config=read_config,
        write_config=write_config,
        credential_restrictions=credential_restrictions,
        git_safe_directories=git_safe_directories,
        bin_shell=bin_shell,
        abort_signal=abort_signal,
        cwd=cwd,
    )


async def _wrap_macos(
    *,
    command: str,
    needs_network_restriction: bool,
    needs_network_proxy: bool,
    read_config: FsReadRestrictionConfig | None,
    write_config: FsWriteRestrictionConfig | None,
    credential_restrictions: CredentialRestrictionConfig,
    allow_pty: bool,
    git_safe_directories: list[str],
    bin_shell: str | None,
) -> list[str]:
    return wrap_command_with_sandbox_macos(
        command=command,
        needs_network_restriction=needs_network_restriction,
        http_proxy_port=(
            get_proxy_port() if needs_network_proxy else None
        ),
        socks_proxy_port=(
            get_socks_proxy_port() if needs_network_proxy else None
        ),
        proxy_auth_token=(
            _proxy_auth_token if needs_network_proxy else None
        ),
        ca_cert_path=None,
        allow_unix_sockets=_get_allow_unix_sockets(),
        allow_all_unix_sockets=False,
        allow_local_binding=bool(_get_allow_local_binding()),
        allow_mach_lookup=_get_allow_mach_lookup(),
        read_config=read_config,
        write_config=write_config,
        unset_env_vars=credential_restrictions["unsetEnvVars"],
        set_env_vars=credential_restrictions["setEnvVars"],
        masked_file_binds=credential_restrictions["maskedFileBinds"],
        ignore_violations=_get_ignore_violations(),
        allow_pty=allow_pty,
        allow_git_config=_get_allow_git_config(),
        git_safe_directories=git_safe_directories,
        enable_weaker_network_isolation=False,
        allow_apple_events=bool(_get_allow_apple_events()),
        bin_shell=bin_shell,
    )


async def _wrap_linux(
    *,
    command: str,
    needs_network_restriction: bool,
    needs_network_proxy: bool,
    read_config: FsReadRestrictionConfig | None,
    write_config: FsWriteRestrictionConfig | None,
    credential_restrictions: CredentialRestrictionConfig,
    git_safe_directories: list[str],
    bin_shell: str | None,
    abort_signal: asyncio.Future | None,
    cwd: str | None,
) -> list[str]:
    return await wrap_command_with_sandbox_linux(
        command=command,
        needs_network_restriction=needs_network_restriction,
        http_socket_path=(
            get_linux_http_socket_path() if needs_network_proxy else None
        ),
        socks_socket_path=(
            get_linux_socks_socket_path() if needs_network_proxy else None
        ),
        http_proxy_port=(
            get_proxy_port() if needs_network_proxy else None
        ),
        socks_proxy_port=(
            get_socks_proxy_port() if needs_network_proxy else None
        ),
        proxy_auth_token=(
            _proxy_auth_token if needs_network_proxy else None
        ),
        ca_cert_path=None,
        read_config=read_config,
        write_config=write_config,
        unset_env_vars=credential_restrictions["unsetEnvVars"],
        set_env_vars=credential_restrictions["setEnvVars"],
        masked_file_binds=credential_restrictions["maskedFileBinds"],
        masked_file_store_dir=credential_restrictions["maskedFileStoreDir"],
        enable_weaker_nested_sandbox=False,
        allow_all_unix_sockets=False,
        bin_shell=bin_shell,
        ripgrep_config=_get_ripgrep_config(),
        mandatory_deny_search_depth=_get_mandatory_deny_search_depth(),
        allow_git_config=_get_allow_git_config(),
        git_safe_directories=git_safe_directories,
        seccomp_config=_get_seccomp_config(),
        bwrap_path=(_config or {}).get("bwrapPath"),
        socat_path=(_config or {}).get("socatPath"),
        observe_socket_path=(
            _linux_monitor.observe_socket_path if _linux_monitor else None
        ),
        abort_signal=abort_signal,
        cwd=cwd,
    )


# ---------------------------------------------------------------------------
# updateConfig / cleanup / reset
# ---------------------------------------------------------------------------

def update_config(new_config: SandboxRuntimeConfig) -> None:
    """Live-swap the allowlist (the proxy reads config per request); the
    filesystem rules are baked at wrap time, like upstream."""
    global _config, _parent_proxy
    _config = deep_clone_config(new_config)
    _parent_proxy = resolve_parent_proxy(
        new_config.get("network", {}).get("parentProxy")
    )
    log_for_debugging("Sandbox configuration updated")


def cleanup_after_command() -> None:
    cleanup_bwrap_mount_points()


async def _reset_infra() -> None:
    global _http_proxy_server, _socks_proxy_server, _mux_proxy_server
    global _manager_context, _proxy_auth_token, _log_monitor_shutdown
    global _linux_monitor, _parent_proxy

    cleanup_bwrap_mount_points(force=True)

    if _log_monitor_shutdown:
        _log_monitor_shutdown()
        _log_monitor_shutdown = None
    if _linux_monitor:
        _linux_monitor.stop()
        _linux_monitor = None

    bridge = (_manager_context or {}).get("linuxBridge")
    if bridge:
        await stop_linux_network_bridge(bridge)

    if _mux_proxy_server:
        await _mux_proxy_server.close()
        _mux_proxy_server = None
    if _http_proxy_server:
        await _http_proxy_server.close()
        _http_proxy_server = None
    if _socks_proxy_server:
        await _socks_proxy_server.close()
        _socks_proxy_server = None

    _manager_context = None
    _proxy_auth_token = None
    _parent_proxy = None


async def reset() -> None:
    """Tear down the whole session (monitors, bridges, proxies, state)."""
    global _config, _initialization_done, _initialization_error
    await _reset_infra()
    _config = None
    _initialization_done = None
    _initialization_error = None
    _sandbox_violation_store.clear()


def get_sandbox_violation_store() -> SandboxViolationStore:
    return _sandbox_violation_store


def annotate_stderr_with_sandbox_failures(command: str, stderr: str) -> str:
    if not _config:
        return stderr
    violations = _sandbox_violation_store.get_violations_for_command(command)
    if not violations:
        return stderr
    annotated = stderr
    annotated += os.linesep + "<sandbox_violations>" + os.linesep
    for violation in violations:
        annotated += violation.line + os.linesep
    annotated += "</sandbox_violations>"
    return annotated


def get_linux_glob_pattern_warnings() -> list[str]:
    if get_platform() != "linux" or not _config:
        return []
    return linux_glob_pattern_warning_paths(_config)


def get_config() -> SandboxRuntimeConfig | None:
    return _config


def get_seccomp_availability() -> bool:
    """Linux readiness helper: seccomp helper verified + on disk."""
    config = _config or {}
    seccomp = config.get("seccomp") or {}
    if seccomp.get("argv0"):
        return True
    return get_apply_seccomp_binary_path(seccomp.get("applyPath")) is not None
