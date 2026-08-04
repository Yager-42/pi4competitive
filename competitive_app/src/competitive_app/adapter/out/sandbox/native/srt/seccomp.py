"""SRT seccomp helper resolution — architecture gating, vendored binary
location, and pinned SHA-256 verification.

Source: sandbox-runtime@0.0.67 ``src/sandbox/generate-seccomp-filter.ts``
Repository: anthropics/sandbox-runtime @ 21d8f75e1bc00eede09b3103e68b2eae097110d1
License: Apache-2.0 (retained under the native sandbox license directory)

Host delta (ADAPT, per G0 map §5): the upstream npm-install/global-npm path
search is replaced by the repo's own vendored tree
(``native/vendor/seccomp/<arch>/apply-seccomp``, npm-published binaries with
pinned SHA-256 from G0 map §5.1) plus an explicit ``applyPath`` override.
Resolution verifies the architecture-specific SHA-256 and the executable
bit before Linux readiness — a tampered or mismatched binary fails closed.
The 32-bit x86 rejection and the global-npm fallback are omitted (no npm at
startup; unsupported architectures fail readiness).
"""
from __future__ import annotations

import hashlib
import os
import platform
from pathlib import Path

from .process import log_for_debugging

# G0 map §5.1 — pinned npm-published binary identities.
APPLY_SECCOMP_SHA256 = {
    "x64": "8e0c58e1ccb0fed7c7d95295773204a2b7e7235c14feac934d7812e7fb2017ab",
    "arm64": "0bec512e784caf7d87f60783ece6480e1340b1ecd38f30b1d6d79d7e794cefb4",
}

_apply_seccomp_path_cache: dict[str, str | None] = {}

_VENDOR_ROOT = Path(__file__).resolve().parent.parent / "vendor" / "seccomp"


def get_vendor_architecture() -> str | None:
    """Map the runtime architecture to the vendor dir name (x64/arm64).

    Only x86-64 and aarch64 are supported, mirroring upstream; anything
    else fails Linux readiness (G0 §5.2.5).
    """
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "x64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    log_for_debugging(
        f"[SeccompFilter] Unsupported architecture: {machine}. "
        "Only x64 and arm64 are supported."
    )
    return None


def verify_apply_seccomp_sha256(path: str) -> bool:
    """True when the file's SHA-256 matches the host architecture pin."""
    expected = APPLY_SECCOMP_SHA256.get(get_vendor_architecture() or "")
    if expected is None:
        return False
    try:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return False
    return digest == expected


def _find_apply_seccomp(explicit_path: str | None) -> str | None:
    # Explicit path first (highest priority); must exist and verify.
    if explicit_path:
        if os.path.exists(explicit_path):
            if not os.access(explicit_path, os.X_OK):
                log_for_debugging(
                    "[SeccompFilter] apply-seccomp binary at explicit path "
                    f"not executable: {explicit_path}",
                    level="error",
                )
                return None
            if not verify_apply_seccomp_sha256(explicit_path):
                log_for_debugging(
                    "[SeccompFilter] apply-seccomp binary at explicit path "
                    f"failed SHA-256 verification: {explicit_path}",
                    level="error",
                )
                return None
            log_for_debugging(
                "[SeccompFilter] Using apply-seccomp binary from explicit "
                f"path: {explicit_path}"
            )
            return explicit_path
        log_for_debugging(
            "[SeccompFilter] Explicit path provided but file not found: "
            f"{explicit_path}"
        )
        return None

    arch = get_vendor_architecture()
    if arch is None:
        return None
    binary_path = _VENDOR_ROOT / arch / "apply-seccomp"
    if not binary_path.exists():
        log_for_debugging(
            f"[SeccompFilter] apply-seccomp binary not found at "
            f"{binary_path} ({arch})"
        )
        return None
    if not os.access(binary_path, os.X_OK):
        log_for_debugging(
            f"[SeccompFilter] apply-seccomp binary not executable: "
            f"{binary_path}",
            level="error",
        )
        return None
    if not verify_apply_seccomp_sha256(str(binary_path)):
        log_for_debugging(
            f"[SeccompFilter] apply-seccomp binary failed SHA-256 "
            f"verification: {binary_path}",
            level="error",
        )
        return None
    log_for_debugging(
        f"[SeccompFilter] Found verified apply-seccomp binary: "
        f"{binary_path} ({arch})"
    )
    return str(binary_path)


def get_apply_seccomp_binary_path(
    seccomp_binary_path: str | None = None,
) -> str | None:
    """Resolve the apply-seccomp binary, verifying exec bit + pinned SHA-256.

    Results are cached per key (explicit path or vendor default) like the
    upstream path cache.
    """
    cache_key = seccomp_binary_path or ""
    if cache_key in _apply_seccomp_path_cache:
        return _apply_seccomp_path_cache[cache_key]
    result = _find_apply_seccomp(seccomp_binary_path)
    _apply_seccomp_path_cache[cache_key] = result
    return result


def get_vendored_license_path() -> Path | None:
    """Path to the retained SRT Apache-2.0 license text (the vendored
    apply-seccomp helper ships under the SRT license; G0 §1.2 pin
    ``1210bc93…`` retained in the native license directory)."""
    license_path = _VENDOR_ROOT.parent / "licenses" / "SRT-APACHE-2.0.txt"
    return license_path if license_path.exists() else None


def reset_seccomp_path_cache() -> None:
    """Test seam: clear the resolution cache."""
    _apply_seccomp_path_cache.clear()
