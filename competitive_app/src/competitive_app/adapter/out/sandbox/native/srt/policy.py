"""SRT policy core — strict config validation, restriction schemas, domain
patterns, and path/glob/proxy-env utilities.

Source: sandbox-runtime@0.0.67 ``src/sandbox/{sandbox-config,sandbox-schemas,domain-pattern,sandbox-utils}.ts``
Repository: anthropics/sandbox-runtime @ 21d8f75e1bc00eede09b3103e68b2eae097110d1
License: Apache-2.0 (retained under the native sandbox license directory)

Host delta (ADAPT, per G0 map §4.1): ``sandbox-config.ts`` is ported as a
strict filesystem/network/seccomp subset — unsupported credential/TLS/Windows
fields (``credentials``, ``tlsTerminate``, ``mitmProxy``, ``filterRequest``,
``parentProxy``, ``windows``, ``srtWin``) and the weakening switches
(``enableWeakerNestedSandbox``, ``enableWeakerNetworkIsolation``,
``allowAllUnixSockets: true``) are REJECTED by validation, not ignored. The
Zod ``superRefine`` cross-checks exist only for masked credentials and are
omitted with the credentials subset. Windows-only sandbox-utils helpers
(stripExtendedPathPrefix/isUncPath/expandWindowsEnvRefs/schannel git config)
are omitted. ``SandboxViolationStore`` folds into ``manager.py`` (target
layout has no separate violation-store file).
"""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Any, TypedDict

from .process import get_platform, log_for_debugging

# ---------------------------------------------------------------------------
# sandbox-config.ts — strict accepted subset
# ---------------------------------------------------------------------------

DANGEROUS_FILES = (
    ".gitconfig",
    ".gitmodules",
    ".bashrc",
    ".bash_profile",
    ".zshrc",
    ".zprofile",
    ".profile",
    ".ripgreprc",
    ".mcp.json",
)

DANGEROUS_DIRECTORIES = (".git", ".vscode", ".idea")

DEFAULT_MANDATORY_DENY_SEARCH_DEPTH = 3

UNSUPPORTED_TOP_LEVEL_FIELDS = (
    "credentials",
    "enableWeakerNestedSandbox",
    "enableWeakerNetworkIsolation",
    "windows",
)

UNSUPPORTED_NETWORK_FIELDS = (
    "mitmProxy",
    "filterRequest",
    "tlsTerminate",
    "parentProxy",
)


class DomainConfigError(ValueError):
    """Raised for any invalid or unsupported SRT configuration."""


class NetworkConfig(TypedDict, total=False):
    allowedDomains: list[str]
    deniedDomains: list[str]
    strictAllowlist: bool
    allowUnixSockets: list[str]
    allowAllUnixSockets: bool
    allowLocalBinding: bool
    allowMachLookup: list[str]
    httpProxyPort: int
    socksProxyPort: int


class FilesystemConfig(TypedDict, total=False):
    disabled: bool
    denyRead: list[str]
    allowRead: list[str]
    allowWrite: list[str]
    denyWrite: list[str]
    allowGitConfig: bool


class SeccompConfig(TypedDict, total=False):
    applyPath: str
    argv0: str


class GitConfig(TypedDict, total=False):
    safeDirectories: list[str]


class RipgrepConfig(TypedDict, total=False):
    command: str
    args: list[str]
    argv0: str


class SandboxRuntimeConfig(TypedDict, total=False):
    network: NetworkConfig
    filesystem: FilesystemConfig
    ignoreViolations: dict[str, list[str]]
    allowAppleEvents: bool
    ripgrep: RipgrepConfig
    mandatoryDenySearchDepth: int
    allowPty: bool
    seccomp: SeccompConfig
    bwrapPath: str
    socatPath: str
    git: GitConfig


def _fail(message: str) -> None:
    raise DomainConfigError(f"invalid sandbox-runtime configuration: {message}")


def _require_dict(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{path} must be an object")
    return value


def _check_unknown_keys(
    value: dict[str, Any], allowed: set[str], path: str
) -> None:
    unknown = [key for key in value if key not in allowed]
    if unknown:
        _fail(f"unknown {path} field(s): {', '.join(sorted(unknown))}")


def validate_domain_pattern(value: Any, path: str) -> str:
    """domainPatternSchema — reject protocols, paths, ports, broad wildcards."""
    if not isinstance(value, str):
        _fail(f"{path} must be a string")
    if "://" in value or "/" in value or ":" in value:
        _fail(
            f"{path} invalid domain pattern {value!r}: "
            "must be a valid domain (e.g. \"example.com\") or wildcard "
            "(e.g. \"*.example.com\")"
        )
    if value == "localhost":
        return value
    if value.startswith("*."):
        domain = value[2:]
        # After the *. there must be a valid domain with at least one more
        # dot: *.example.com is valid, *.com is not (too broad).
        if (
            "." not in domain
            or domain.startswith(".")
            or domain.endswith(".")
        ):
            _fail(f"{path} invalid domain pattern {value!r}: too broad")
        parts = domain.split(".")
        if not (len(parts) >= 2 and all(len(p) > 0 for p in parts)):
            _fail(f"{path} invalid domain pattern {value!r}: too broad")
        return value
    if "*" in value:
        _fail(f"{path} invalid domain pattern {value!r}: wildcard not allowed")
    if not (
        "." in value and not value.startswith(".") and not value.endswith(".")
    ):
        _fail(f"{path} invalid domain pattern {value!r}: must contain a dot")
    return value


def _validate_domain_list(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(v, str) for v in value
    ):
        _fail(f"{path} must be an array of strings")
    for i, entry in enumerate(value):
        validate_domain_pattern(entry, f"{path}[{i}]")
    return list(value)


def _validate_path_list(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(v, str) and v != "" for v in value
    ):
        _fail(f"{path} must be an array of non-empty strings")
    return list(value)


def _validate_binary_path(value: Any, path: str) -> str:
    if not isinstance(value, str) or value == "":
        _fail(f"{path} must be a non-empty string")
    if not os.path.isabs(value):
        _fail(f"{path} must be an absolute path")
    return value


def _validate_network(value: dict[str, Any], path: str) -> NetworkConfig:
    allowed = {
        "allowedDomains",
        "deniedDomains",
        "strictAllowlist",
        "allowUnixSockets",
        "allowAllUnixSockets",
        "allowLocalBinding",
        "allowMachLookup",
        "httpProxyPort",
        "socksProxyPort",
        *UNSUPPORTED_NETWORK_FIELDS,
    }
    _check_unknown_keys(value, allowed, path)
    for field in UNSUPPORTED_NETWORK_FIELDS:
        if field in value:
            _fail(
                f"{path}.{field} is not supported by this port; "
                "supplying it must fail validation instead of silently "
                "weakening"
            )

    result: NetworkConfig = {}
    if "allowedDomains" in value:
        result["allowedDomains"] = _validate_domain_list(
            value["allowedDomains"], f"{path}.allowedDomains"
        )
    if "deniedDomains" in value:
        denied = value["deniedDomains"]
        if not isinstance(denied, list) or not all(
            isinstance(v, str) for v in denied
        ):
            _fail(f"{path}.deniedDomains must be an array of strings")
        for i, entry in enumerate(denied):
            if entry != "*":
                validate_domain_pattern(entry, f"{path}.deniedDomains[{i}]")
        result["deniedDomains"] = list(denied)
    for field in ("strictAllowlist", "allowAllUnixSockets", "allowLocalBinding"):
        if field in value:
            if not isinstance(value[field], bool):
                _fail(f"{path}.{field} must be a boolean")
            result[field] = value[field]  # type: ignore[literal-required]
    if result.get("allowAllUnixSockets") is True:
        _fail(
            f"{path}.allowAllUnixSockets is not exposed as a production "
            "weakening switch; only false is accepted"
        )
    if "allowUnixSockets" in value:
        result["allowUnixSockets"] = _validate_path_list(
            value["allowUnixSockets"], f"{path}.allowUnixSockets"
        )
    if "allowMachLookup" in value:
        mach = value["allowMachLookup"]
        if not isinstance(mach, list) or not all(
            isinstance(v, str) for v in mach
        ):
            _fail(f"{path}.allowMachLookup must be an array of strings")
        for i, entry in enumerate(mach):
            prefix = entry[:-1] if entry.endswith("*") else entry
            if "*" in prefix:
                _fail(
                    f"{path}.allowMachLookup[{i}] wildcards are only allowed "
                    'as a single trailing "*"'
                )
        result["allowMachLookup"] = list(mach)
    for field in ("httpProxyPort", "socksProxyPort"):
        if field in value:
            port = value[field]
            if (
                not isinstance(port, int)
                or isinstance(port, bool)
                or not 1 <= port <= 65535
            ):
                _fail(f"{path}.{field} must be an integer in 1..65535")
            result[field] = port  # type: ignore[literal-required]
    return result


def _validate_filesystem(
    value: dict[str, Any], path: str
) -> FilesystemConfig:
    allowed = {
        "disabled",
        "denyRead",
        "allowRead",
        "allowWrite",
        "denyWrite",
        "allowGitConfig",
    }
    _check_unknown_keys(value, allowed, path)
    result: FilesystemConfig = {}
    for field in ("disabled", "allowGitConfig"):
        if field in value:
            if not isinstance(value[field], bool):
                _fail(f"{path}.{field} must be a boolean")
            result[field] = value[field]  # type: ignore[literal-required]
    for field in ("denyRead", "allowRead", "allowWrite", "denyWrite"):
        if field in value:
            result[field] = _validate_path_list(  # type: ignore[literal-required]
                value[field], f"{path}.{field}"
            )
    return result


def _validate_mach_lookup(value: Any, path: str) -> None:
    _require_dict(value, path)
    _check_unknown_keys(value, set(), path)


def validate_sandbox_runtime_config(
    data: Any, *, platform: str | None = None
) -> SandboxRuntimeConfig:
    """Strict validation of the accepted SRT config subset.

    Mirrors the upstream Zod schemas for the supported filesystem/network/
    seccomp subset; every unsupported field fails loudly. ``platform`` is
    accepted for signature parity (upstream validates platform-agnostically
    too — Linux/macOS-specific fields are validated but applied per
    platform at wrap time).
    """
    del platform
    if not isinstance(data, dict):
        _fail("root must be an object")
    allowed = {
        "network",
        "filesystem",
        "ignoreViolations",
        "allowAppleEvents",
        "ripgrep",
        "mandatoryDenySearchDepth",
        "allowPty",
        "seccomp",
        "bwrapPath",
        "socatPath",
        "git",
        *UNSUPPORTED_TOP_LEVEL_FIELDS,
    }
    _check_unknown_keys(data, allowed, "root")
    for field in UNSUPPORTED_TOP_LEVEL_FIELDS:
        if field in data:
            _fail(
                f"{field} is not supported by this port; supplying it must "
                "fail validation instead of silently weakening"
            )

    result: SandboxRuntimeConfig = {}

    if "network" in data:
        result["network"] = _validate_network(
            _require_dict(data["network"], "network"), "network"
        )
    if "filesystem" in data:
        result["filesystem"] = _validate_filesystem(
            _require_dict(data["filesystem"], "filesystem"), "filesystem"
        )
    if "ignoreViolations" in data:
        ignore = data["ignoreViolations"]
        if not isinstance(ignore, dict) or not all(
            isinstance(k, str)
            and isinstance(v, list)
            and all(isinstance(p, str) for p in v)
            for k, v in ignore.items()
        ):
            _fail(
                "ignoreViolations must be a map of command patterns to "
                "arrays of paths"
            )
        result["ignoreViolations"] = {
            k: list(v) for k, v in ignore.items()
        }
    for field, check in (
        ("allowAppleEvents", bool),
        ("allowPty", bool),
    ):
        if field in data:
            if not isinstance(data[field], check):
                _fail(f"{field} must be a boolean")
            result[field] = data[field]  # type: ignore[literal-required]
    if "mandatoryDenySearchDepth" in data:
        depth = data["mandatoryDenySearchDepth"]
        if (
            not isinstance(depth, int)
            or isinstance(depth, bool)
            or not 1 <= depth <= 10
        ):
            _fail("mandatoryDenySearchDepth must be an integer in 1..10")
        result["mandatoryDenySearchDepth"] = depth
    if "ripgrep" in data:
        rg = _require_dict(data["ripgrep"], "ripgrep")
        _check_unknown_keys(rg, {"command", "args", "argv0"}, "ripgrep")
        if "command" in rg:
            if not isinstance(rg["command"], str) or rg["command"] == "":
                _fail("ripgrep.command must be a non-empty string")
        if "args" in rg and (
            not isinstance(rg["args"], list)
            or not all(isinstance(a, str) for a in rg["args"])
        ):
            _fail("ripgrep.args must be an array of strings")
        if "argv0" in rg and not isinstance(rg["argv0"], str):
            _fail("ripgrep.argv0 must be a string")
        result["ripgrep"] = {  # type: ignore[literal-required]
            key: list(rg[key]) if key == "args" else rg[key]
            for key in rg
        }
    if "seccomp" in data:
        sc = _require_dict(data["seccomp"], "seccomp")
        _check_unknown_keys(sc, {"applyPath", "argv0"}, "seccomp")
        seccomp: SeccompConfig = {}
        if "applyPath" in sc:
            seccomp["applyPath"] = _validate_binary_path(
                sc["applyPath"], "seccomp.applyPath"
            )
        if "argv0" in sc:
            if not isinstance(sc["argv0"], str):
                _fail("seccomp.argv0 must be a string")
            seccomp["argv0"] = sc["argv0"]
        if seccomp.get("argv0") and not seccomp.get("applyPath"):
            _fail("seccomp.argv0 requires seccomp.applyPath")
        result["seccomp"] = seccomp
    for field in ("bwrapPath", "socatPath"):
        if field in data:
            result[field] = _validate_binary_path(  # type: ignore[literal-required]
                data[field], field
            )
    if "git" in data:
        git = _require_dict(data["git"], "git")
        _check_unknown_keys(git, {"safeDirectories"}, "git")
        if "safeDirectories" in git:
            result["git"] = {
                "safeDirectories": _validate_path_list(
                    git["safeDirectories"], "git.safeDirectories"
                )
            }
    return result


def deep_clone_config(config: SandboxRuntimeConfig) -> SandboxRuntimeConfig:
    """Structured clone equivalent for updateConfig (no functions here)."""
    return json.loads(
        json.dumps(config, separators=(",", ":"), default=dict)
    )


# ---------------------------------------------------------------------------
# domain-pattern.ts — matchesDomainPattern
# ---------------------------------------------------------------------------

def _is_ip_literal(host: str) -> bool:
    """Best-effort IP literal detection (IPv4, or IPv6 without zone ids)."""
    if ":" in host:
        return True
    try:
        import ipaddress

        ipaddress.IPv4Address(host)
        return True
    except ValueError:
        return False


def matches_domain_pattern(hostname: str, pattern: str) -> bool:
    """Match a hostname against a domain pattern (exact or ``*.base``).

    COPY-semantics from upstream: ``*`` matches everything; ``*.example.com``
    matches strict subdomains only; anything else matches exactly
    (case-insensitive). Wildcard suffix matching is refused for IP literals.
    """
    host = hostname.lower()
    if pattern == "*":
        return True
    if pattern.startswith("*."):
        if _is_ip_literal(host.strip("[]")):
            return False
        base_domain = pattern[2:].lower()
        return host.endswith("." + base_domain)
    return host == pattern.lower()


# ---------------------------------------------------------------------------
# sandbox-schemas.ts — internal restriction shapes
# ---------------------------------------------------------------------------

class FsReadRestrictionConfig(TypedDict, total=False):
    denyOnly: list[str]
    allowWithinDeny: list[str]


class FsWriteRestrictionConfig(TypedDict):
    allowOnly: list[str]
    denyWithinAllow: list[str]


class CredentialRestrictionConfig(TypedDict):
    denyReadPaths: list[str]
    unsetEnvVars: list[str]
    setEnvVars: dict[str, str]
    maskedFileBinds: list[dict[str, str]]
    maskedFileStoreDir: str | None


class NetworkRestrictionConfig(TypedDict, total=False):
    allowedHosts: list[str]
    deniedHosts: list[str]


def empty_credential_restrictions() -> CredentialRestrictionConfig:
    """Credential configuration is rejected by validation, so the runtime
    seam always resolves to the empty shape (erichll never configures it)."""
    return {
        "denyReadPaths": [],
        "unsetEnvVars": [],
        "setEnvVars": {},
        "maskedFileBinds": [],
        "maskedFileStoreDir": None,
    }


# ---------------------------------------------------------------------------
# sandbox-utils.ts — shared path/glob/proxy-env helpers (POSIX subset)
# ---------------------------------------------------------------------------

def get_dangerous_directories() -> list[str]:
    """Dangerous dirs minus .git (git needs hooks/config handled separately)."""
    return [
        *[d for d in DANGEROUS_DIRECTORIES if d != ".git"],
        ".claude/commands",
        ".claude/agents",
    ]


def normalize_case_for_comparison(path_str: str) -> str:
    return path_str.lower()


def contains_glob_chars(path_pattern: str) -> bool:
    return any(ch in path_pattern for ch in "*?[]")


def remove_trailing_glob_suffix(path_pattern: str) -> str:
    stripped = re.sub(r"/\*\*$", "", path_pattern)
    return stripped or "/"


def is_symlink_outside_boundary(original_path: str, resolved_path: str) -> bool:
    """True when a symlink resolution broadens scope beyond the original path."""
    normalized_original = os.path.normpath(original_path)
    normalized_resolved = os.path.normpath(resolved_path)

    if normalized_resolved == normalized_original:
        return False

    # macOS /tmp -> /private/tmp canonical resolution is legitimate
    if normalized_original.startswith("/tmp/") and normalized_resolved == (
        "/private" + normalized_original
    ):
        return False
    if normalized_original.startswith("/var/") and normalized_resolved == (
        "/private" + normalized_original
    ):
        return False
    if normalized_original.startswith("/private/tmp/") and normalized_resolved == normalized_original:
        return False
    if normalized_original.startswith("/private/var/") and normalized_resolved == normalized_original:
        return False

    if normalized_resolved == "/":
        return True
    resolved_parts = [p for p in normalized_resolved.split("/") if p]
    if len(resolved_parts) <= 1:
        return True
    if normalized_original.startswith(normalized_resolved + "/"):
        return True

    canonical_original = normalized_original
    if normalized_original.startswith("/tmp/"):
        canonical_original = "/private" + normalized_original
    elif normalized_original.startswith("/var/"):
        canonical_original = "/private" + normalized_original

    if (
        canonical_original != normalized_original
        and canonical_original.startswith(normalized_resolved + "/")
    ):
        return True

    resolved_starts_with_original = normalized_resolved.startswith(
        normalized_original + "/"
    )
    resolved_starts_with_canonical = (
        canonical_original != normalized_original
        and normalized_resolved.startswith(canonical_original + "/")
    )
    resolved_is_canonical = (
        canonical_original != normalized_original
        and normalized_resolved == canonical_original
    )
    resolved_is_same = normalized_resolved == normalized_original

    if (
        not resolved_is_same
        and not resolved_is_canonical
        and not resolved_starts_with_original
        and not resolved_starts_with_canonical
    ):
        return True
    return False


def expand_tilde(path_str: str) -> str:
    if path_str == "~":
        return os.path.expanduser("~")
    if path_str.startswith("~/"):
        return os.path.expanduser("~") + path_str[1:]
    return path_str


def normalize_path_for_sandbox(path_pattern: str) -> str:
    """Absolute path with symlinks resolved (or normalized glob pattern).

    POSIX subset of the upstream function: tilde expansion, relative-path
    resolution against cwd, symlink realpath gated by the boundary check;
    glob patterns keep their wildcards (static prefix resolved when safe).
    """
    cwd = os.getcwd()
    normalized_path = expand_tilde(path_pattern)

    if normalized_path != path_pattern:
        pass
    elif path_pattern.startswith(("./", "../")):
        normalized_path = os.path.abspath(os.path.join(cwd, path_pattern))
    elif not os.path.isabs(path_pattern):
        normalized_path = os.path.abspath(os.path.join(cwd, path_pattern))

    if contains_glob_chars(normalized_path):
        split_re = re.compile(r"[*?\[\]]")
        static_prefix = split_re.split(normalized_path)[0]
        if static_prefix and static_prefix != "/":
            base_dir = (
                static_prefix[:-1]
                if static_prefix.endswith("/")
                else os.path.dirname(static_prefix)
            )
            try:
                resolved_base_dir = os.path.realpath(base_dir)
                if not is_symlink_outside_boundary(base_dir, resolved_base_dir):
                    pattern_suffix = normalized_path[len(base_dir):]
                    return resolved_base_dir + pattern_suffix
            except OSError:
                pass
        return normalized_path

    try:
        resolved_path = os.path.realpath(normalized_path)
        if not is_symlink_outside_boundary(normalized_path, resolved_path):
            normalized_path = resolved_path
    except OSError:
        pass
    return normalized_path


def get_default_write_paths() -> list[str]:
    home_dir = os.path.expanduser("~")
    return [
        "/dev/stdout",
        "/dev/stderr",
        "/dev/null",
        "/dev/tty",
        "/dev/dtracehelper",
        "/dev/autofs_nowait",
        "/tmp/claude",
        "/private/tmp/claude",
        os.path.join(home_dir, ".npm/_logs"),
        os.path.join(home_dir, ".claude/debug"),
    ]


CA_TRUST_VARS = (
    "NODE_EXTRA_CA_CERTS",
    "SSL_CERT_FILE",
    "CURL_CA_BUNDLE",
    "REQUESTS_CA_BUNDLE",
    "PIP_CERT",
    "GIT_SSL_CAINFO",
    "AWS_CA_BUNDLE",
    "CARGO_HTTP_CAINFO",
    "DENO_CERT",
    "CLOUDSDK_CORE_CUSTOM_CA_CERTS_FILE",
    "NIX_SSL_CERT_FILE",
)

_NO_PROXY_ADDRESSES = ",".join(
    [
        "localhost",
        "127.0.0.1",
        "::1",
        "169.254.0.0/16",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
    ]
)


def generate_proxy_env_vars(
    http_proxy_port: int | None = None,
    socks_proxy_port: int | None = None,
    ca_cert_path: str | None = None,
    proxy_auth_token: str | None = None,
    skip_tmpdir: bool = False,
) -> list[str]:
    """Proxy environment variables for the sandboxed child — exact port.

    TLS trust vars and the GIT_CONFIG_PARAMETERS injection are omitted with
    the TLS-termination/credential subsets; the rest (TMPDIR override,
    NO_PROXY, HTTP(S)_PROXY, ALL_PROXY, GRPC_PROXY, FTP/RSYNC/DOCKER/
    CLOUDSDK vars, GIT_SSH_COMMAND) is preserved verbatim, including the
    macOS ``nc -X 5`` and Linux ``socat PROXY:`` git-over-ssh variants.
    """
    auth = f"srt:{proxy_auth_token}@" if proxy_auth_token else ""
    env_vars: list[str] = ["SANDBOX_RUNTIME=1"]
    if not skip_tmpdir:
        tmpdir = (
            os.environ.get("CLAUDE_CODE_TMPDIR")
            or os.environ.get("CLAUDE_TMPDIR")
            or "/tmp/claude"
        )
        env_vars.append(f"TMPDIR={tmpdir}")

    if ca_cert_path:
        for var in CA_TRUST_VARS:
            env_vars.append(f"{var}={ca_cert_path}")

    if not http_proxy_port and not socks_proxy_port:
        return env_vars

    env_vars.append(f"NO_PROXY={_NO_PROXY_ADDRESSES}")
    env_vars.append(f"no_proxy={_NO_PROXY_ADDRESSES}")

    if http_proxy_port:
        env_vars.append(f"HTTP_PROXY=http://{auth}localhost:{http_proxy_port}")
        env_vars.append(f"HTTPS_PROXY=http://{auth}localhost:{http_proxy_port}")
        env_vars.append(f"http_proxy=http://{auth}localhost:{http_proxy_port}")
        env_vars.append(f"https_proxy=http://{auth}localhost:{http_proxy_port}")
        if proxy_auth_token:
            env_vars.append(
                "GIT_CONFIG_PARAMETERS='http.proxyAuthMethod=basic'"
            )

    connect_proxy_url = (
        f"http://{auth}localhost:{http_proxy_port}"
        if http_proxy_port
        else f"socks5h://{auth}localhost:{socks_proxy_port}"
    )
    env_vars.append(f"ALL_PROXY={connect_proxy_url}")
    env_vars.append(f"all_proxy={connect_proxy_url}")
    env_vars.append(f"GRPC_PROXY={connect_proxy_url}")
    env_vars.append(f"grpc_proxy={connect_proxy_url}")

    if socks_proxy_port:
        ssh_mux_override = "-o ControlMaster=no -o ControlPath=none"
        platform = get_platform()
        if platform == "macos":
            env_vars.append(
                f"GIT_SSH_COMMAND=ssh {ssh_mux_override} -o ProxyCommand='nc -X 5 "
                f"-x localhost:{socks_proxy_port} %h %p'"
            )
        elif platform == "linux" and http_proxy_port:
            socat_auth = (
                f",proxyauth=srt:{proxy_auth_token}" if proxy_auth_token else ""
            )
            env_vars.append(
                f"GIT_SSH_COMMAND=ssh {ssh_mux_override} -o ProxyCommand='socat - "
                f"PROXY:localhost:%h:%p,proxyport={http_proxy_port}{socat_auth}'"
            )

        env_vars.append(
            f"FTP_PROXY=socks5h://{auth}localhost:{socks_proxy_port}"
        )
        env_vars.append(
            f"ftp_proxy=socks5h://{auth}localhost:{socks_proxy_port}"
        )
        env_vars.append(f"RSYNC_PROXY=localhost:{socks_proxy_port}")
        env_vars.append(
            f"DOCKER_HTTP_PROXY=http://{auth}localhost:"
            f"{http_proxy_port or socks_proxy_port}"
        )
        env_vars.append(
            f"DOCKER_HTTPS_PROXY=http://{auth}localhost:"
            f"{http_proxy_port or socks_proxy_port}"
        )
        if http_proxy_port:
            env_vars.append("CLOUDSDK_PROXY_TYPE=http")
            env_vars.append("CLOUDSDK_PROXY_ADDRESS=localhost")
            env_vars.append(f"CLOUDSDK_PROXY_PORT={http_proxy_port}")
            if proxy_auth_token:
                env_vars.append("CLOUDSDK_PROXY_USERNAME=srt")
                env_vars.append(f"CLOUDSDK_PROXY_PASSWORD={proxy_auth_token}")

    return env_vars


SAFE_DIRECTORY_WILDCARD_THRESHOLD = 8


def _git_safe_dir_values(safe_dirs: list[str]) -> list[str]:
    dirs: list[str] = []
    for d in safe_dirs:
        if not d:
            continue
        fwd = d.replace("\\", "/")
        stripped = re.sub(r"/+$", "", fwd)
        if stripped == "":
            stripped = "/"
        dirs.append(stripped)
    return list(dict.fromkeys(dirs))


def build_git_config_env(
    safe_dirs: list[str],
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """GIT_CONFIG_COUNT / KEY_n / VALUE_n env set for the child.

    POSIX subset: ``safe.directory`` exact path + ``<dir>/*`` glob per entry
    (or a single ``safe.directory=*`` above the wildcard threshold); the
    Windows schannel knobs are omitted. An explicit ``GIT_CONFIG_COUNT=0`` in
    base_env is respected as an opt-out.
    """
    base = base_env or {}
    if base.get("GIT_CONFIG_COUNT") == "0":
        return {}
    try:
        start = max(0, int(base.get("GIT_CONFIG_COUNT", "") or 0))
    except ValueError:
        start = 0
    n = start
    out: dict[str, str] = {}

    def emit(key: str, value: str) -> None:
        nonlocal n
        out[f"GIT_CONFIG_KEY_{n}"] = key
        out[f"GIT_CONFIG_VALUE_{n}"] = value
        n += 1

    dirs = _git_safe_dir_values(safe_dirs)
    if len(dirs) > SAFE_DIRECTORY_WILDCARD_THRESHOLD:
        emit("safe.directory", "*")
    else:
        for d in dirs:
            emit("safe.directory", d)
            emit("safe.directory", f"{d}/*" if not d.endswith("/") else f"{d}*")
    if n == start:
        return {}
    out["GIT_CONFIG_COUNT"] = str(n)
    return out


def build_posix_git_safe_dir_env(
    safe_dirs: list[str],
    unset_env_vars: list[str] | None = None,
    set_env_vars: dict[str, str] | None = None,
) -> dict[str, str]:
    """Compose safe.directory env against the child's inherited env."""
    base_env: dict[str, str] = {}
    if os.environ.get("GIT_CONFIG_COUNT") is not None:
        base_env["GIT_CONFIG_COUNT"] = os.environ["GIT_CONFIG_COUNT"]
    for key in unset_env_vars or []:
        base_env.pop(key, None)
    base_env.update(set_env_vars or {})
    return build_git_config_env(safe_dirs, base_env)


def encode_sandboxed_command(command: str) -> str:
    """Truncate to 100 chars and base64-encode (violation log tag parity)."""
    return base64.b64encode(command[:100].encode("utf-8")).decode("ascii")


def decode_sandboxed_command(encoded_command: str) -> str:
    return base64.b64decode(encoded_command.encode("ascii")).decode("utf-8")


def glob_to_regex(glob_pattern: str) -> str:
    """gitignore-style glob -> anchored regex (the ``ignore``-library subset).

    Exact port of the upstream algorithm including the placeholder dance:
    ``*`` matches non-``/``, ``**`` matches anything, ``**/`` matches zero or
    more dirs, ``?`` matches one non-``/`` char, ``[abc]`` char sets, unclosed
    brackets escaped.
    """
    escaped = re.sub(r"[.^$+{}()|\\]", r"\\\g<0>", glob_pattern)
    # Escape unclosed brackets (no matching ]) — regex substitution, not a
    # literal replace, mirroring the upstream .replace(/\[([^\]]*?)$/g, ...).
    escaped = re.sub(r"\[([^\]]*?)$", r"\\[\1", escaped)
    return (
        "^"
        + escaped.replace("**/", "__GLOBSTAR_SLASH__")
        .replace("**", "__GLOBSTAR__")
        .replace("*", "[^/]*")
        .replace("?", "[^/]")
        .replace("__GLOBSTAR_SLASH__", "(.*/)?")
        .replace("__GLOBSTAR__", ".*")
        + "$"
    )


def expand_glob_pattern(
    glob_path: str,
    *,
    case_insensitive: bool = False,
) -> list[str]:
    """Expand a glob into concrete paths (Linux bwrap needs real paths)."""
    normalized_pattern = normalize_path_for_sandbox(glob_path)

    static_prefix = re.split(r"[*?\[\]]", normalized_pattern)[0]
    if not static_prefix or static_prefix == "/":
        log_for_debugging(
            f"[Sandbox] Glob pattern too broad, skipping: {glob_path}"
        )
        return []

    base_dir = (
        static_prefix[:-1]
        if static_prefix.endswith("/")
        else os.path.dirname(static_prefix)
    )
    if not os.path.exists(base_dir):
        log_for_debugging(
            f"[Sandbox] Base directory for glob does not exist: {base_dir}"
        )
        return []

    pattern = glob_to_regex(normalized_pattern)
    flags = re.IGNORECASE if case_insensitive else 0
    regex = re.compile(pattern, flags)
    for root, dirs, files in os.walk(base_dir, followlinks=False):
        for name in files + dirs:
            full_path = os.path.join(root, name)
            if regex.match(full_path):
                results.append(full_path)
    return results


def linux_glob_pattern_warning_paths(config: SandboxRuntimeConfig) -> list[str]:
    """Glob patterns in allowWrite/denyWrite unsupported on Linux bwrap."""
    fs = config.get("filesystem")
    if not fs or fs.get("disabled"):
        return []
    glob_patterns: list[str] = []
    for path_str in [*(fs.get("allowWrite") or []), *(fs.get("denyWrite") or [])]:
        path_without_trailing = remove_trailing_glob_suffix(path_str)
        if contains_glob_chars(path_without_trailing):
            glob_patterns.append(path_str)
    return glob_patterns
