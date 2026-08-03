"""Concrete capability-side types (COPY of ``src/broker/types.ts`` concrete
side + ``src/integrations/sandbox.ts`` trap schema).

Source: pi-auto-review@0.3.2 ``src/broker/types.ts`` / ``src/integrations/sandbox.ts``
Repository: erichll/pi-packages @ 10c8eeb8269ee478ff7383c7e6139301aa9665f9
License: MIT (retained under the native sandbox license directory)

Host delta (COPY-semantics): the generic boundary contract (``BoundaryRequest``,
``BoundaryReview``, ``BoundaryDecision``, …) lives in
``earendil_works.pi_agent.boundary_approval`` per ADR 0013 D-NSBX5; this module
re-exports the capability's concrete policy/review types so tests and the
reviewer import from one capability surface. The sandbox trap schema is the
auto-review-owned exported surface (``@erichll/pi-auto-review/sandbox``);
the App's ``native/traps.py`` re-exports it and ``approval/sandbox.py``
implements the boundary-request conversion.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import NotRequired, TypeAlias, TypedDict

from earendil_works.pi_agent.boundary_approval import (
    AllowDecision,
    BoundaryApprovalBrokerService,
    BoundaryAuditEvent,
    BoundaryDecision,
    BoundaryGrant,
    BoundaryHardDeny,
    BoundaryRequest,
    BoundaryReview,
    BoundaryReviewContext,
    BoundaryReviewer,
    BoundaryReviewerContext,
    BoundaryRiskLevel,
    BoundarySource,
    BoundarySurface,
    DeferDecision,
    DenyDecision,
    HardDenyResult,
    UserAuthorization,
)

from .policy import (
    Evidence,
    ModelDecision,
    PermissionDetailsLike,
    RelevantBoundaryRequest,
    TranscriptConfig,
    TranscriptResult,
)

AuditCallback = Callable[[BoundaryAuditEvent], None]


# ---------------------------------------------------------------------------
# Sandbox boundary traps (src/integrations/sandbox.ts)
# ---------------------------------------------------------------------------

class SandboxProcessInfo(TypedDict, total=False):
    pid: int
    exe: str | None
    cwd: str | None


class _SandboxFilesystemTrapRequired(TypedDict):
    kind: str  # literal "filesystem"
    operation: str  # literal "read" | "write"
    path: str


class SandboxFilesystemTrap(_SandboxFilesystemTrapRequired, total=False):
    requested_path: str
    reason: str
    query_id: str
    process: SandboxProcessInfo


class _SandboxNetworkTrapRequired(TypedDict):
    kind: str  # literal "network"
    operation: str  # literal "connect" | "bind"
    target: str


class SandboxNetworkTrap(_SandboxNetworkTrapRequired, total=False):
    query_id: str
    process: SandboxProcessInfo


SandboxBoundaryTrap: TypeAlias = SandboxFilesystemTrap | SandboxNetworkTrap


class SandboxRequestContext(TypedDict):
    cwd: str
    command: NotRequired[str]
    agentName: NotRequired[str]


__all__ = [
    "AllowDecision",
    "AuditCallback",
    "BoundaryApprovalBrokerService",
    "BoundaryAuditEvent",
    "BoundaryDecision",
    "BoundaryGrant",
    "BoundaryHardDeny",
    "BoundaryRequest",
    "BoundaryReview",
    "BoundaryReviewContext",
    "BoundaryReviewer",
    "BoundaryReviewerContext",
    "BoundaryRiskLevel",
    "BoundarySource",
    "BoundarySurface",
    "DeferDecision",
    "DenyDecision",
    "Evidence",
    "HardDenyResult",
    "ModelDecision",
    "PermissionDetailsLike",
    "RelevantBoundaryRequest",
    "SandboxBoundaryTrap",
    "SandboxFilesystemTrap",
    "SandboxNetworkTrap",
    "SandboxProcessInfo",
    "SandboxRequestContext",
    "TranscriptConfig",
    "TranscriptResult",
    "UserAuthorization",
]
