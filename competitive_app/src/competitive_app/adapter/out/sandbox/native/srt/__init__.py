"""SRT (sandbox-runtime) Python port — native Linux/macOS sandbox core.

Source: sandbox-runtime@0.0.67 @ 21d8f75e1bc00eede09b3103e68b2eae097110d1
License: Apache-2.0 (retained under native/vendor/licenses/SRT-APACHE-2.0.txt)

Port layout (G0 map §4.1): policy (config/schemas/domain/path-utils),
linux (bwrap/bridge/deny scan/monitor), macos (Seatbelt/log monitor),
seccomp (vendored helper + pinned hashes), proxy (HTTP/SOCKS/mux/parent),
process (debug/platform/ripgrep/shell-quote/which), manager (session state
+ violation store). ``src/index.ts`` is omitted; consumers use the
explicit module symbols.
"""
from __future__ import annotations

from .manager import (
    SandboxViolationStore,
    annotate_stderr_with_sandbox_failures,
    check_dependencies,
    check_dependencies_async,
    cleanup_after_command,
    filter_network_request,
    get_config,
    get_linux_glob_pattern_warnings,
    get_network_restriction_config,
    get_proxy_auth_token,
    get_proxy_port,
    get_sandbox_violation_store,
    get_seccomp_availability,
    get_socks_proxy_port,
    initialize,
    is_sandboxing_enabled,
    is_supported_platform,
    reset,
    update_config,
    wait_for_network_initialization,
    wrap_with_sandbox,
)
from .policy import (
    FsReadRestrictionConfig,
    FsWriteRestrictionConfig,
    SandboxRuntimeConfig,
    validate_sandbox_runtime_config,
)
from .seccomp import (
    get_apply_seccomp_binary_path,
    verify_apply_seccomp_sha256,
)

__all__ = [
    "FsReadRestrictionConfig",
    "FsWriteRestrictionConfig",
    "SandboxRuntimeConfig",
    "SandboxViolationStore",
    "annotate_stderr_with_sandbox_failures",
    "check_dependencies",
    "check_dependencies_async",
    "cleanup_after_command",
    "filter_network_request",
    "get_apply_seccomp_binary_path",
    "get_config",
    "get_linux_glob_pattern_warnings",
    "get_network_restriction_config",
    "get_proxy_auth_token",
    "get_proxy_port",
    "get_sandbox_violation_store",
    "get_seccomp_availability",
    "get_socks_proxy_port",
    "initialize",
    "is_sandboxing_enabled",
    "is_supported_platform",
    "reset",
    "update_config",
    "validate_sandbox_runtime_config",
    "verify_apply_seccomp_sha256",
    "wait_for_network_initialization",
    "wrap_with_sandbox",
]
