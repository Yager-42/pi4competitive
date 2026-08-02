"""App sandbox trap types/formatter (COPY-semantics).

Source: pi-sandbox@0.4.2 ``src/traps.ts``
Repository: erichll/pi-packages @ 10c8eeb8269ee478ff7383c7e6139301aa9665f9
License: Apache-2.0 (retained under the native sandbox license directory)

Host delta: the trap schema re-exported here is the auto-review-owned surface
(``pi_auto_review.types``), mirroring the upstream re-export from
``@erichll/pi-auto-review/sandbox``.
"""
from __future__ import annotations

from typing import TypeAlias

from pi_auto_review.types import (
    SandboxBoundaryTrap,
    SandboxFilesystemTrap,
    SandboxNetworkTrap,
)

SandboxApprovalTrap: TypeAlias = SandboxBoundaryTrap
SandboxApprovalAction: TypeAlias = str  # literal "allow" | "deny"


def format_sandbox_trap(trap: SandboxApprovalTrap) -> str:
    if trap["kind"] == "filesystem":
        return f"{trap['operation']} {trap['path']}"
    return f"{trap['operation']} {trap['target']}"


__all__ = [
    "SandboxApprovalAction",
    "SandboxApprovalTrap",
    "SandboxBoundaryTrap",
    "SandboxFilesystemTrap",
    "SandboxNetworkTrap",
    "format_sandbox_trap",
]
