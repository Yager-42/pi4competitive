"""Generic boundary-approval service seam (Pi Agent core, provider-neutral).

Source: pi-auto-review@0.3.2 ``src/broker/types.ts`` + ``src/broker/service.ts``
Repository: erichll/pi-packages @ 10c8eeb8269ee478ff7383c7e6139301aa9665f9
License: MIT (retained under the native sandbox license directory)

Host delta (ADAPT):
- TypeScript global ``Symbol.for`` publication becomes a module-level Python
  registry keyed by an explicit string; publication/unpublication semantics and
  the double-publish error are preserved.
- The published service exposes only ``review`` / ``consumeGrant`` (upstream
  service.ts shape). The full broker (hard deny, breaker, grants) lives in the
  local ``pi_auto_review`` capability package; this module must never import
  App, sandbox, OS, or policy implementation.
- Typed unions become ``TypedDict`` kinds (``kind: "allow" | "deny" | "defer"``).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal, NotRequired, Protocol, TypeAlias, TypedDict, runtime_checkable

BoundarySurface: TypeAlias = str
BoundarySource: TypeAlias = str


class BoundaryRequest(TypedDict):
    id: str
    source: BoundarySource
    surface: BoundarySurface
    operation: str
    cwd: str
    command: NotRequired[str]
    path: NotRequired[str]
    resolvedPath: NotRequired[str]
    destination: NotRequired[str]
    toolCallId: NotRequired[str]
    toolName: NotRequired[str]
    skillName: NotRequired[str]
    toolInputPreview: NotRequired[str]
    agentName: NotRequired[str]
    matchedPolicy: NotRequired[dict[str, str | None]]


BoundaryRiskLevel: TypeAlias = Literal["low", "medium", "high", "critical"]
UserAuthorization: TypeAlias = Literal["unknown", "low", "medium", "high"]


class BoundaryReview(TypedDict):
    outcome: Literal["allow", "deny", "defer"]
    riskLevel: BoundaryRiskLevel
    userAuthorization: UserAuthorization
    rationale: str


class BoundaryGrant(TypedDict):
    token: str
    requestHash: str
    sessionId: str
    expiresAt: int
    usesRemaining: Literal[1]


class AllowDecision(TypedDict):
    kind: Literal["allow"]
    review: BoundaryReview
    grant: NotRequired[BoundaryGrant]


class DenyDecision(TypedDict):
    kind: Literal["deny"]
    review: BoundaryReview
    circuitBreakerTripped: bool


class DeferDecision(TypedDict):
    kind: Literal["defer"]
    review: BoundaryReview


BoundaryDecision: TypeAlias = AllowDecision | DenyDecision | DeferDecision


class BoundaryReviewContext(TypedDict):
    sessionId: str
    scopeKey: str
    issueGrant: NotRequired[bool]


class BoundaryUserOverride(TypedDict):
    originalRequestId: str
    approvedAt: int


class BoundaryReviewerContext(TypedDict):
    userOverride: NotRequired[BoundaryUserOverride]


class BoundaryAuditEvent(TypedDict):
    type: Literal[
        "hard_deny",
        "review_decision",
        "review_failure",
        "circuit_breaker",
        "grant_issued",
        "grant_consumed",
        "grant_rejected",
        "override_authorized",
        "override_consumed",
    ]
    requestId: str
    surface: str
    details: dict[str, object]


class HardDenyResult(TypedDict):
    rule: str
    reason: str


BoundaryReviewer: TypeAlias = Callable[
    [BoundaryRequest, BoundaryReviewerContext | None],
    Awaitable[BoundaryReview],
]
BoundaryHardDeny: TypeAlias = Callable[[BoundaryRequest], HardDenyResult | None]


@runtime_checkable
class BoundaryApprovalBrokerService(Protocol):
    """Generic published seam: exact review decision + one-shot grant consume."""

    async def review(
        self,
        request: BoundaryRequest,
        context: BoundaryReviewContext,
    ) -> BoundaryDecision: ...

    def consumeGrant(
        self,
        request: BoundaryRequest,
        sessionId: str,
        token: str,
    ) -> bool: ...


# Service key mirrors upstream ``Symbol.for("pi-auto-review:boundary-approval-broker")``.
BOUNDARY_BROKER_SERVICE_KEY = "pi-auto-review:boundary-approval-broker"

_registry: dict[str, BoundaryApprovalBrokerService] = {}


def publish_boundary_broker(
    broker: BoundaryApprovalBrokerService,
) -> Callable[[], None]:
    """Publish *broker* under the canonical service key; returns an unpublisher.

    Publishing twice without unpublishing raises (upstream ``publishBoundaryBroker``).
    """
    if BOUNDARY_BROKER_SERVICE_KEY in _registry:
        raise RuntimeError("pi-auto-review boundary broker is already published")
    _registry[BOUNDARY_BROKER_SERVICE_KEY] = broker
    published = broker

    def unpublish() -> None:
        if _registry.get(BOUNDARY_BROKER_SERVICE_KEY) is published:
            _registry.pop(BOUNDARY_BROKER_SERVICE_KEY, None)

    return unpublish


def get_boundary_broker() -> BoundaryApprovalBrokerService | None:
    """Look up the published broker service, if any."""
    return _registry.get(BOUNDARY_BROKER_SERVICE_KEY)


__all__ = [
    "BOUNDARY_BROKER_SERVICE_KEY",
    "AllowDecision",
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
    "BoundaryUserOverride",
    "DeferDecision",
    "DenyDecision",
    "HardDenyResult",
    "UserAuthorization",
    "get_boundary_broker",
    "publish_boundary_broker",
]
