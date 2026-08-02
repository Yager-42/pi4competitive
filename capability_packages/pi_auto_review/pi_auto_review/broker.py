"""Boundary approval broker — hard deny -> breaker -> reviewer -> exact grant.

Source: pi-auto-review@0.3.2 ``src/broker/broker.ts``
Repository: erichll/pi-packages @ 10c8eeb8269ee478ff7383c7e6139301aa9665f9
License: MIT (retained under the native sandbox license directory)

Host delta (ADAPT):
- Python async instead of JS promises; explicit constructor DI (reviewer,
  hardDeny, failureMode, grants, breaker, audit) per ADR 0012 D-NSBX5.
- The ``RecentDenialStore`` paths (``recentDenials`` / ``authorizeRecentDenial``
  and the userOverride branch of ``review``) are OMIT — G0 map §3.1
  ``overrides.ts`` OMIT: no user retry/TUI entry exists in this host.
- Validation, hard-deny, breaker, reviewer, failure-mode, and one-shot grant
  semantics are preserved exactly.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from earendil_works.pi_agent.boundary_approval import (
    BoundaryAuditEvent,
    BoundaryDecision,
    BoundaryHardDeny,
    BoundaryRequest,
    BoundaryReview,
    BoundaryReviewContext,
    BoundaryReviewer,
)

from .circuit_breaker import DenialCircuitBreaker
from .grants import OneShotGrantStore

FAILURE_REVIEW: BoundaryReview = {
    "outcome": "deny",
    "riskLevel": "high",
    "userAuthorization": "unknown",
    "rationale": "Automatic review is unavailable.",
}

AuditCallback = Callable[[BoundaryAuditEvent], None]


class BoundaryApprovalBrokerOptions:
    def __init__(
        self,
        *,
        reviewer: BoundaryReviewer,
        hardDeny: BoundaryHardDeny | None = None,
        failureMode: str = "deny",
        grants: OneShotGrantStore | None = None,
        breaker: DenialCircuitBreaker | None = None,
        audit: AuditCallback | None = None,
    ) -> None:
        self.reviewer = reviewer
        self.hardDeny = hardDeny
        self.failureMode = failureMode
        self.grants = grants
        self.breaker = breaker
        self.audit = audit


def _assert_request(request: BoundaryRequest) -> None:
    for name, value in (
        ("id", request.get("id")),
        ("source", request.get("source")),
        ("surface", request.get("surface")),
        ("operation", request.get("operation")),
        ("cwd", request.get("cwd")),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"boundary request {name} must be a non-empty string")


class BoundaryApprovalBroker:
    """Fail-closed per-request approval: exact hash, one-shot grant, breaker."""

    def __init__(self, options: BoundaryApprovalBrokerOptions) -> None:
        self._reviewer: BoundaryReviewer = options.reviewer
        self._hardDeny: BoundaryHardDeny | None = options.hardDeny
        self._failureMode: str = options.failureMode or "deny"
        self._grants: OneShotGrantStore = options.grants or OneShotGrantStore()
        self._breaker: DenialCircuitBreaker = options.breaker or DenialCircuitBreaker()
        self._audit: AuditCallback | None = options.audit

    async def review(
        self,
        request: BoundaryRequest,
        context: BoundaryReviewContext,
    ) -> BoundaryDecision:
        _assert_request(request)
        hard_deny = self._hardDeny(request) if self._hardDeny is not None else None
        if hard_deny:
            breaker = self._breaker.record(context["scopeKey"], True)
            review: BoundaryReview = {
                "outcome": "deny",
                "riskLevel": "critical",
                "userAuthorization": "unknown",
                "rationale": hard_deny["reason"],
            }
            self._audit_event("hard_deny", request, {
                "rule": hard_deny["rule"],
                "reason": hard_deny["reason"],
            })
            if breaker["tripped"]:
                self._audit_event("circuit_breaker", request, breaker)
            return {
                "kind": "deny",
                "review": review,
                "circuitBreakerTripped": breaker["tripped"],
            }

        if self._breaker.is_tripped(context["scopeKey"]):
            review = {
                **FAILURE_REVIEW,
                "rationale": "Automatic review stopped after repeated denials in this turn.",
            }
            self._audit_event("circuit_breaker", request, {"scopeKey": context["scopeKey"]})
            return {"kind": "deny", "review": review, "circuitBreakerTripped": True}

        try:
            review = await self._reviewer(request, None)
        except Exception as error:  # noqa: BLE001
            reason = (
                f"Automatic review is unavailable: "
                f"{error if isinstance(error, Exception) else str(error)}"
            )
            self._audit_event("review_failure", request, {"reason": reason})
            if self._failureMode == "defer":
                self._breaker.record(context["scopeKey"], False)
                return {
                    "kind": "defer",
                    "review": {**FAILURE_REVIEW, "outcome": "defer", "rationale": reason},
                }
            breaker = self._breaker.record(context["scopeKey"], True)
            return {
                "kind": "deny",
                "review": {**FAILURE_REVIEW, "rationale": reason},
                "circuitBreakerTripped": breaker["tripped"],
            }

        self._audit_event("review_decision", request, review)
        if review["outcome"] == "deny":
            breaker = self._breaker.record(context["scopeKey"], True)
            if breaker["tripped"]:
                self._audit_event("circuit_breaker", request, breaker)
            return {
                "kind": "deny",
                "review": review,
                "circuitBreakerTripped": breaker["tripped"],
            }

        self._breaker.record(context["scopeKey"], False)
        if review["outcome"] == "defer":
            return {"kind": "defer", "review": review}

        grant = (
            self._grants.issue(request, context["sessionId"])
            if context.get("issueGrant")
            else None
        )
        if grant is not None:
            self._audit_event("grant_issued", request, {
                "requestHash": grant["requestHash"],
                "expiresAt": grant["expiresAt"],
            })
        return {"kind": "allow", "review": review, **({"grant": grant} if grant else {})}

    def consumeGrant(
        self,
        request: BoundaryRequest,
        session_id: str,
        token: str,
    ) -> bool:
        consumed = self._grants.consume(request, session_id, token)
        self._audit_event(
            "grant_consumed" if consumed else "grant_rejected",
            request,
            {"sessionId": session_id},
        )
        return consumed

    def clear(self) -> None:
        self._grants.clear()
        self._breaker.clear()

    def _audit_event(
        self,
        type_: str,
        request: BoundaryRequest,
        details: dict[str, Any],
    ) -> None:
        if self._audit is None:
            return
        self._audit({
            "type": type_,
            "requestId": request.get("id", ""),
            "surface": request.get("surface", ""),
            "details": details,
        })


__all__ = ["FAILURE_REVIEW", "BoundaryApprovalBroker", "BoundaryApprovalBrokerOptions"]
