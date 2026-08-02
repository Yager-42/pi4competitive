"""Concrete capability-side types (COPY of ``src/broker/types.ts`` concrete side).

Source: pi-auto-review@0.3.2 ``src/broker/types.ts``
Repository: erichll/pi-packages @ 10c8eeb8269ee478ff7383c7e6139301aa9665f9
License: MIT (retained under the native sandbox license directory)

Host delta (COPY-semantics): the generic boundary contract (``BoundaryRequest``,
``BoundaryReview``, ``BoundaryDecision``, …) lives in
``earendil_works.pi_agent.boundary_approval`` per ADR 0012 D-NSBX5; this module
re-exports the capability's concrete policy/review types so tests and the
reviewer import from one capability surface.
"""
from __future__ import annotations

from collections.abc import Callable

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
    "TranscriptConfig",
    "TranscriptResult",
    "UserAuthorization",
]
