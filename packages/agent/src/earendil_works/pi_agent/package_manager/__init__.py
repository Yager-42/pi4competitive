"""Local isomorphic subset of coding-agent package-manager.

upstream: packages/coding-agent/src/core/package-manager.ts (+ resource-loader, extensions/loader)
ADR 0006 / contract v0.3.2 — local capability_packages only; install/npm/git/home omitted.
"""
from __future__ import annotations

from pathlib import Path

from .apply import apply_capability_report, merge_tools
from .errors import (
    PackageLoadError,
    PackageManagerError,
    PackageNotFoundError,
    UnsupportedInstallError,
)
from .extensions_loader import CapabilityRegisterApi, load_extension_module, load_extensions
from .package_manager import LocalPackageManager, default_capability_root, resource_precedence_rank
from .resource_loader import materialize_resolved
from .types import (
    PACKAGE_ROOT_DEFAULT,
    LoadReport,
    LoadedPackage,
    PathMetadata,
    PiManifest,
    ResolvedPaths,
    ResolvedResource,
    ResourceDiagnostic,
)


async def load_capability_packages(
    root: Path | str | None = None,
    *,
    enabled: list[str] | None = None,
    disabled: list[str] | None = None,
    strict: bool = False,
    cwd: Path | str | None = None,
) -> LoadReport:
    """Discover, resolve, and load local capability packages.

    *root* defaults to ``<cwd>/capability_packages``.
    """
    pm = LocalPackageManager(root, enabled=enabled, disabled=disabled, cwd=cwd)
    if strict and not pm.root.is_dir():
        raise PackageNotFoundError(f"capability packages root missing: {pm.root}")
    resolved = await pm.resolve()
    return materialize_resolved(resolved, root=pm.root, strict=strict)


def load_capability_packages_sync(
    root: Path | str | None = None,
    *,
    enabled: list[str] | None = None,
    disabled: list[str] | None = None,
    strict: bool = False,
    cwd: Path | str | None = None,
) -> LoadReport:
    """Sync convenience wrapper around :func:`load_capability_packages`."""
    pm = LocalPackageManager(root, enabled=enabled, disabled=disabled, cwd=cwd)
    if strict and not pm.root.is_dir():
        raise PackageNotFoundError(f"capability packages root missing: {pm.root}")
    resolved = pm.resolve_sync()
    return materialize_resolved(resolved, root=pm.root, strict=strict)


__all__ = [
    "PACKAGE_ROOT_DEFAULT",
    "CapabilityRegisterApi",
    "LoadReport",
    "LoadedPackage",
    "LocalPackageManager",
    "PackageLoadError",
    "PackageManagerError",
    "PackageNotFoundError",
    "PathMetadata",
    "PiManifest",
    "ResolvedPaths",
    "ResolvedResource",
    "ResourceDiagnostic",
    "UnsupportedInstallError",
    "apply_capability_report",
    "default_capability_root",
    "load_capability_packages",
    "load_capability_packages_sync",
    "load_extension_module",
    "load_extensions",
    "merge_tools",
    "resource_precedence_rank",
]
