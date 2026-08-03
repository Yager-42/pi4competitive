"""O15 — SRT seccomp helper resolution + pinned SHA-256 verification.

Source parity: sandbox-runtime@0.0.67 seccomp tests (PORT, offline subset).
License: Apache-2.0 (retained under the native sandbox license directory)
"""
from __future__ import annotations

import os

import pytest

from competitive_app.adapter.out.sandbox.native.srt import seccomp
from competitive_app.adapter.out.sandbox.native.srt.seccomp import (
    APPLY_SECCOMP_SHA256,
    get_apply_seccomp_binary_path,
    get_vendor_architecture,
    reset_seccomp_path_cache,
    verify_apply_seccomp_sha256,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_seccomp_path_cache()
    yield
    reset_seccomp_path_cache()


def test_pinned_hashes_present() -> None:
    assert set(APPLY_SECCOMP_SHA256) == {"x64", "arm64"}
    assert len(APPLY_SECCOMP_SHA256["x64"]) == 64
    assert len(APPLY_SECCOMP_SHA256["arm64"]) == 64


def test_vendor_architecture_current_machine() -> None:
    arch = get_vendor_architecture()
    # macOS arm64 / linux x86_64 hosts map into the supported set
    assert arch in ("x64", "arm64")


def test_unsupported_architecture_fails_readiness(monkeypatch) -> None:
    monkeypatch.setattr(seccomp.platform, "machine", lambda: "ia32")
    assert get_vendor_architecture() is None
    assert get_apply_seccomp_binary_path() is None


def test_vendored_binary_resolves_and_verifies() -> None:
    binary = get_apply_seccomp_binary_path()
    if binary is None:
        pytest.skip("no vendored binary for this architecture")
    assert os.path.exists(binary)
    assert os.access(binary, os.X_OK)
    assert verify_apply_seccomp_sha256(binary)


def test_vendored_binary_matches_g0_pin(tmp_path) -> None:
    # Verify the on-disk vendor file against the G0 map §5.1 hash directly.
    vendor_dir = (
        seccomp._VENDOR_ROOT
        / (get_vendor_architecture() or "arm64")
        / "apply-seccomp"
    )
    if not vendor_dir.exists():
        pytest.skip("no vendored binary for this architecture")
    assert verify_apply_seccomp_sha256(str(vendor_dir))


def test_tampered_binary_fails_verification(tmp_path) -> None:
    arch = get_vendor_architecture() or "arm64"
    target = tmp_path / "apply-seccomp"
    target.write_bytes(b"#!/bin/sh\necho fake\n")
    assert not verify_apply_seccomp_sha256(str(target))
    assert get_apply_seccomp_binary_path(str(target)) is None


def test_explicit_path_missing_returns_none() -> None:
    assert get_apply_seccomp_binary_path("/nonexistent/apply-seccomp") is None


def test_cache_is_per_key(monkeypatch) -> None:
    calls: list[str] = []
    real_find = seccomp._find_apply_seccomp

    def _counting_find(explicit: str | None) -> str | None:
        calls.append(explicit or "")
        return real_find(explicit)

    monkeypatch.setattr(seccomp, "_find_apply_seccomp", _counting_find)
    get_apply_seccomp_binary_path(None)
    get_apply_seccomp_binary_path(None)
    assert len(calls) == 1
    reset_seccomp_path_cache()
    get_apply_seccomp_binary_path(None)
    assert len(calls) == 2


def test_vendored_license_retained() -> None:
    license_path = seccomp.get_vendored_license_path()
    assert license_path is not None and license_path.exists()
