"""Package-manager errors (local subset)."""
from __future__ import annotations


class PackageManagerError(Exception):
    """Base error for local package manager."""


class PackageLoadError(PackageManagerError):
    """Failed to load a capability package or extension module."""


class PackageNotFoundError(PackageManagerError):
    """Local package path missing (strict mode)."""


class UnsupportedInstallError(PackageManagerError, NotImplementedError):
    """Install/update/remove surfaces are omitted (ADR 0006 D-PM3)."""


__all__ = [
    "PackageLoadError",
    "PackageManagerError",
    "PackageNotFoundError",
    "UnsupportedInstallError",
]
