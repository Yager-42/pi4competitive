"""O9 — broker: validate -> hard deny -> breaker -> reviewer -> exact grant.

Source: pi-auto-review@0.3.2 ``broker.test.ts`` (validation/reviewer/grant/breaker
cases; denial-override and audit cases preserved where applicable)
"""
from __future__ import annotations

import pytest
from earendil_works.pi_agent.boundary_approval import BoundaryRequest
from pi_auto_review.broker import BoundaryApprovalBroker, BoundaryApprovalBrokerOptions


def _request(**overrides: object) -> BoundaryRequest:
    base: dict[str, object] = {
        "id": "r1",
        "source": "sandbox-runtime",
        "surface": "network",
        "operation": "connect",
        "cwd": "/tmp/workspace",
        "destination": "api.example.com:443",
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


def _allow_reviewer() -> object:
    async def reviewer(_request: object, _context: object) -> dict[str, str]:
        return {"outcome": "allow", "riskLevel": "low", "userAuthorization": "unknown", "rationale": "ok"}
    return reviewer


def _deny_reviewer() -> object:
    async def reviewer(_request: object, _context: object) -> dict[str, str]:
        return {"outcome": "deny", "riskLevel": "high", "userAuthorization": "unknown", "rationale": "blocked"}
    return reviewer


def _defer_reviewer() -> object:
    async def reviewer(_request: object, _context: object) -> dict[str, str]:
        return {"outcome": "defer", "riskLevel": "medium", "userAuthorization": "unknown", "rationale": "uncertain"}
    return reviewer


def _make(reviewer: object = None, **options: object) -> BoundaryApprovalBroker:
    return BoundaryApprovalBroker(
        BoundaryApprovalBrokerOptions(
            reviewer=reviewer if reviewer is not None else _allow_reviewer(),
            **options,
        )
    )


@pytest.mark.asyncio
async def test_validation_rejects_empty_fields() -> None:
    broker = _make()
    for field in ("id", "source", "surface", "operation", "cwd"):
        request = _request(**{field: ""})
        with pytest.raises(ValueError, match=f"boundary request {field} must be a non-empty string"):
            await broker.review(request, {"sessionId": "s", "scopeKey": "k"})


@pytest.mark.asyncio
async def test_allow_issues_exact_grant_when_requested() -> None:
    broker = _make()
    request = _request()
    decision = await broker.review(request, {"sessionId": "s", "scopeKey": "k", "issueGrant": True})
    assert decision["kind"] == "allow"
    grant = decision["grant"]
    assert grant is not None
    assert broker.consumeGrant(request, "s", grant["token"]) is True
    assert broker.consumeGrant(request, "s", grant["token"]) is False


@pytest.mark.asyncio
async def test_allow_without_issue_grant_has_no_grant() -> None:
    broker = _make()
    decision = await broker.review(_request(), {"sessionId": "s", "scopeKey": "k"})
    assert decision["kind"] == "allow"
    assert "grant" not in decision


@pytest.mark.asyncio
async def test_hard_deny_wins_over_reviewer() -> None:
    async def never_called(_request: object, _context: object) -> dict[str, str]:
        raise AssertionError("reviewer must not run after a hard deny")

    broker = _make(
        reviewer=never_called,
        hardDeny=lambda _request: {"rule": "test-rule", "reason": "blocked for test"},
    )
    decision = await broker.review(_request(), {"sessionId": "s", "scopeKey": "k"})
    assert decision["kind"] == "deny"
    assert decision["review"]["riskLevel"] == "critical"
    assert decision["review"]["rationale"] == "blocked for test"
    assert decision["circuitBreakerTripped"] is False


@pytest.mark.asyncio
async def test_hard_deny_trips_breaker_after_limit() -> None:
    broker = _make(
        hardDeny=lambda _request: {"rule": "test-rule", "reason": "blocked"},
        breaker=None,
    )
    # Default breaker limit is 3 consecutive; use a small custom breaker.
    from pi_auto_review.circuit_breaker import DenialCircuitBreaker

    small = DenialCircuitBreaker(consecutive_limit=2)
    broker = _make(hardDeny=lambda _request: {"rule": "r", "reason": "b"}, breaker=small)
    first = await broker.review(_request(), {"sessionId": "s", "scopeKey": "k"})
    second = await broker.review(_request(), {"sessionId": "s", "scopeKey": "k"})
    assert first["circuitBreakerTripped"] is False
    assert second["circuitBreakerTripped"] is True


@pytest.mark.asyncio
async def test_tripped_breaker_denies_before_reviewer() -> None:
    async def never_called(_request: object, _context: object) -> dict[str, str]:
        raise AssertionError("reviewer must not run when the breaker is tripped")

    broker = _make(reviewer=never_called)
    broker._breaker.record("k", True)
    broker._breaker.record("k", True)
    broker._breaker.record("k", True)
    decision = await broker.review(_request(), {"sessionId": "s", "scopeKey": "k"})
    assert decision["kind"] == "deny"
    assert decision["circuitBreakerTripped"] is True
    assert "repeated denials" in decision["review"]["rationale"]


@pytest.mark.asyncio
async def test_reviewer_deny_records_breaker() -> None:
    from pi_auto_review.circuit_breaker import DenialCircuitBreaker

    breaker = DenialCircuitBreaker(consecutive_limit=2)
    broker = _make(reviewer=_deny_reviewer(), breaker=breaker)
    decision = await broker.review(_request(), {"sessionId": "s", "scopeKey": "k"})
    assert decision["kind"] == "deny"
    assert decision["review"]["rationale"] == "blocked"
    assert decision["circuitBreakerTripped"] is False
    assert breaker.record("k", False)["consecutiveDenials"] == 0  # untouched scope reset semantics


@pytest.mark.asyncio
async def test_reviewer_defer_returns_defer() -> None:
    broker = _make(reviewer=_defer_reviewer())
    decision = await broker.review(_request(), {"sessionId": "s", "scopeKey": "k"})
    assert decision["kind"] == "defer"
    assert decision["review"]["rationale"] == "uncertain"


@pytest.mark.asyncio
async def test_reviewer_failure_fails_closed_with_deny() -> None:
    async def failing(_request: object, _context: object) -> dict[str, str]:
        raise RuntimeError("model exploded")

    broker = _make(reviewer=failing, failureMode="deny")
    decision = await broker.review(_request(), {"sessionId": "s", "scopeKey": "k"})
    assert decision["kind"] == "deny"
    assert decision["review"]["outcome"] == "deny"
    assert "Automatic review is unavailable" in decision["review"]["rationale"]
    assert "model exploded" in decision["review"]["rationale"]


@pytest.mark.asyncio
async def test_reviewer_failure_defers_in_defer_mode() -> None:
    async def failing(_request: object, _context: object) -> dict[str, str]:
        raise RuntimeError("model exploded")

    broker = _make(reviewer=failing, failureMode="defer")
    decision = await broker.review(_request(), {"sessionId": "s", "scopeKey": "k"})
    assert decision["kind"] == "defer"
    assert decision["review"]["outcome"] == "defer"


@pytest.mark.asyncio
async def test_reviewer_failure_trips_breaker_in_deny_mode() -> None:
    async def failing(_request: object, _context: object) -> dict[str, str]:
        raise RuntimeError("boom")

    from pi_auto_review.circuit_breaker import DenialCircuitBreaker

    breaker = DenialCircuitBreaker(consecutive_limit=2)
    broker = _make(reviewer=failing, breaker=breaker, failureMode="deny")
    await broker.review(_request(), {"sessionId": "s", "scopeKey": "k"})
    decision = await broker.review(_request(), {"sessionId": "s", "scopeKey": "k"})
    assert decision["circuitBreakerTripped"] is True


@pytest.mark.asyncio
async def test_audit_events_emitted_in_order() -> None:
    events: list[dict[str, object]] = []

    def audit(event: dict[str, object]) -> None:
        events.append(event)

    broker = _make(audit=audit)
    request = _request()
    decision = await broker.review(request, {"sessionId": "s", "scopeKey": "k", "issueGrant": True})
    assert [event["type"] for event in events] == ["review_decision", "grant_issued"]
    assert events[0]["requestId"] == "r1"
    assert events[0]["surface"] == "network"
    broker.consumeGrant(request, "s", decision["grant"]["token"])
    assert events[-1]["type"] == "grant_consumed"
    broker.consumeGrant(request, "s", "stale-token")
    assert events[-1]["type"] == "grant_rejected"


@pytest.mark.asyncio
async def test_hard_deny_audit_event() -> None:
    events: list[dict[str, object]] = []

    def audit(event: dict[str, object]) -> None:
        events.append(event)

    broker = _make(
        hardDeny=lambda _request: {"rule": "r", "reason": "b"},
        audit=audit,
    )
    await broker.review(_request(), {"sessionId": "s", "scopeKey": "k"})
    assert events[0]["type"] == "hard_deny"
    assert events[0]["details"] == {"rule": "r", "reason": "b"}


@pytest.mark.asyncio
async def test_clear_resets_grants_and_breaker() -> None:
    broker = _make()
    request = _request()
    decision = await broker.review(request, {"sessionId": "s", "scopeKey": "k", "issueGrant": True})
    broker.clear()
    assert broker.consumeGrant(request, "s", decision["grant"]["token"]) is False
