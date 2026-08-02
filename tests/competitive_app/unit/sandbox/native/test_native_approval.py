"""Approval adapter vectors (PORT of pi-sandbox approval.test.ts minus the
omitted host-IPC product).

Source: pi-sandbox@0.4.2 ``approval.test.ts``
License: Apache-2.0 (retained under the native sandbox license directory)

Host delta: ``approveHostIPCExecution`` is OMIT per G0 §2.1; the negative
contract test asserts the symbol does not exist.
"""
from __future__ import annotations

import asyncio

import pytest

from competitive_app.adapter.out.sandbox.native.approval import (
    NetworkEndpoint,
    TrapApprovalContext,
    TrapApprovalResult,
    approve_domain_endpoint,
    approve_sandbox_trap,
)
from earendil_works.pi_agent.boundary_approval import (
    BoundaryApprovalBrokerService,
    BoundaryDecision,
)
from pi_auto_review.broker import BoundaryApprovalBroker, BoundaryApprovalBrokerOptions

FILESYSTEM_TRAP = {
    "kind": "filesystem",
    "query_id": "7",
    "operation": "read",
    "path": "/home/user/secret",
    "requested_path": "secret",
    "reason": "allow_miss",
    "process": {"pid": 42, "exe": "/usr/bin/cat", "cwd": "/repo"},
}

NETWORK_TRAP = {
    "kind": "network",
    "query_id": "8",
    "operation": "connect",
    "target": "93.184.216.34:443",
    "process": {"pid": 43, "exe": "/usr/bin/curl", "cwd": "/repo"},
}

REVIEW = {
    "outcome": "allow",
    "riskLevel": "low",
    "userAuthorization": "medium",
    "rationale": "Narrow read authorized by the user.",
}

CONTEXT: TrapApprovalContext = {
    "command": "cat secret",
    "cwd": "/repo",
    "sessionId": "session-1",
    "scopeKey": "session-1:turn:3",
}


def broker_for(
    decision: BoundaryDecision,
    consume: bool = True,
) -> tuple[BoundaryApprovalBrokerService, dict[str, int]]:
    counts = {"consumed": 0, "reviewed": 0}

    class _Fake:
        async def review(self, request, context):
            counts["reviewed"] += 1
            return decision

        def consumeGrant(self, request, session_id, token):
            counts["consumed"] += 1
            return consume

    return _Fake(), counts  # type: ignore[return-value]


def test_domain_approval_consumes_grant_bound_to_exact_hostname_and_port() -> None:
    destinations: list[str] = []

    async def reviewer(request, _context):
        destinations.append(request.get("destination") or "")
        return REVIEW

    broker = BoundaryApprovalBroker(
        BoundaryApprovalBrokerOptions(reviewer=reviewer)
    )
    result = asyncio.run(
        approve_domain_endpoint(
            {"hostname": "registry.npmjs.org", "port": 443, "protocol": "https"},
            {**CONTEXT, "broker": broker},
        )
    )
    assert result["action"] == "allow"
    assert result["source"] == "reviewer"
    assert destinations == ["registry.npmjs.org:443"]


def test_allows_only_after_consuming_the_exact_reviewer_grant() -> None:
    fake, counts = broker_for(
        {
            "kind": "allow",
            "review": REVIEW,
            "grant": {
                "token": "token",
                "requestHash": "hash",
                "sessionId": "session-1",
                "expiresAt": 2_000_000_000_000,
                "usesRemaining": 1,
            },
        }
    )
    result = asyncio.run(
        approve_sandbox_trap(FILESYSTEM_TRAP, {**CONTEXT, "broker": fake})
    )
    assert result["action"] == "allow"
    assert result["source"] == "reviewer"
    assert counts["consumed"] == 1


def test_direct_ip_network_traps_cannot_bypass_domain_approval() -> None:
    fake, counts = broker_for(
        {
            "kind": "allow",
            "review": REVIEW,
            "grant": {
                "token": "network-token",
                "requestHash": "hash",
                "sessionId": "session-1",
                "expiresAt": 2_000_000_000_000,
                "usesRemaining": 1,
            },
        }
    )
    result = asyncio.run(
        approve_sandbox_trap(NETWORK_TRAP, {**CONTEXT, "broker": fake})
    )
    assert result["action"] == "deny"
    assert result["source"] == "hard-deny"
    assert counts["reviewed"] == 0
    assert counts["consumed"] == 0


def test_completes_real_broker_grant_issue_and_consume_lifecycle() -> None:
    audit_types: list[str] = []

    async def reviewer(request, _context):
        return REVIEW

    broker = BoundaryApprovalBroker(
        BoundaryApprovalBrokerOptions(
            reviewer=reviewer,
            audit=lambda event: audit_types.append(event["type"]),
        )
    )
    result = asyncio.run(
        approve_sandbox_trap(FILESYSTEM_TRAP, {**CONTEXT, "broker": broker})
    )
    assert result["action"] == "allow"
    assert audit_types == ["review_decision", "grant_issued", "grant_consumed"]


def test_fails_closed_when_reviewer_grant_cannot_be_consumed() -> None:
    fake, _counts = broker_for(
        {
            "kind": "allow",
            "review": REVIEW,
            "grant": {
                "token": "token",
                "requestHash": "hash",
                "sessionId": "session-1",
                "expiresAt": 2_000_000_000_000,
                "usesRemaining": 1,
            },
        },
        consume=False,
    )
    result = asyncio.run(
        approve_sandbox_trap(FILESYSTEM_TRAP, {**CONTEXT, "broker": fake})
    )
    assert result["action"] == "deny"
    assert result["source"] == "invalid-grant"


def test_uses_human_only_for_defer_or_unavailable_broker() -> None:
    fake, _counts = broker_for(
        {"kind": "defer", "review": {**REVIEW, "outcome": "defer"}}
    )
    prompts = 0

    async def human_approval(request, reason=None, signal=None):
        nonlocal prompts
        prompts += 1
        return "allow-once"

    async def run() -> list[TrapApprovalResult]:
        deferred = await approve_sandbox_trap(
            FILESYSTEM_TRAP, {**CONTEXT, "broker": fake, "humanApproval": human_approval}
        )
        unavailable = await approve_sandbox_trap(
            FILESYSTEM_TRAP, {**CONTEXT, "humanApproval": human_approval}
        )
        return [deferred, unavailable]

    deferred, unavailable = asyncio.run(run())
    assert deferred["action"] == "allow"
    assert unavailable["action"] == "allow"
    assert prompts == 2


async def _run_abort_deny() -> TrapApprovalResult:
    signal = asyncio.get_running_loop().create_future()
    signal.set_result(None)

    async def human_approval(request, reason=None, signal=None):
        raise AssertionError("must not prompt after abort")

    return await approve_sandbox_trap(
        FILESYSTEM_TRAP,
        {**CONTEXT, "signal": signal, "humanApproval": human_approval},
    )


def test_human_unavailable_when_no_human_or_signal_aborted() -> None:
    result = asyncio.run(
        approve_sandbox_trap(FILESYSTEM_TRAP, {**CONTEXT})
    )
    assert result["action"] == "deny"
    assert result["source"] == "unavailable"

    aborted = asyncio.run(_run_abort_deny())
    assert aborted["action"] == "deny"
    assert aborted["source"] == "unavailable"


def test_never_sends_explicit_deny_match_to_model_or_human() -> None:
    fake, counts = broker_for({"kind": "allow", "review": REVIEW})
    prompted = False

    async def human_approval(request, reason=None, signal=None):
        nonlocal prompted
        prompted = True
        return "allow-once"

    result = asyncio.run(
        approve_sandbox_trap(
            {**FILESYSTEM_TRAP, "reason": "deny_match"},
            {**CONTEXT, "broker": fake, "humanApproval": human_approval},
        )
    )
    assert result["action"] == "deny"
    assert result["source"] == "hard-deny"
    assert counts["reviewed"] == 0
    assert prompted is False


def test_explicit_reviewer_denial_cannot_be_overridden_by_human() -> None:
    fake, _counts = broker_for(
        {"kind": "deny", "review": {**REVIEW, "outcome": "deny"}, "circuitBreakerTripped": False}
    )
    prompted = False

    async def human_approval(request, reason=None, signal=None):
        nonlocal prompted
        prompted = True
        return "allow-once"

    result = asyncio.run(
        approve_sandbox_trap(
            FILESYSTEM_TRAP, {**CONTEXT, "broker": fake, "humanApproval": human_approval}
        )
    )
    assert result["action"] == "deny"
    assert prompted is False


def test_broker_protocol_failure_cannot_be_overridden_by_human() -> None:
    prompted = False

    class _Broken:
        async def review(self, request, context):
            raise RuntimeError("service invariant failed")

        def consumeGrant(self, request, session_id, token):
            return False

    async def human_approval(request, reason=None, signal=None):
        nonlocal prompted
        prompted = True
        return "allow-once"

    result = asyncio.run(
        approve_sandbox_trap(
            FILESYSTEM_TRAP,
            {**CONTEXT, "broker": _Broken(), "humanApproval": human_approval},
        )
    )
    assert result["action"] == "deny"
    assert result["source"] == "unavailable"
    assert prompted is False


def test_no_host_ipc_symbol_exists() -> None:
    """G0 §2.2 host-ipc.test.ts OMIT: negative contract proof."""
    import competitive_app.adapter.out.sandbox.native.approval as approval

    assert not hasattr(approval, "approve_host_ipc_execution")
    assert not hasattr(approval, "HostIPCTrigger")
    import competitive_app.adapter.out.sandbox.native as native

    assert not hasattr(native, "host_ipc")


def test_domain_endpoint_uses_sandbox_runtime_identity() -> None:
    seen: list[dict] = []

    class _Capturing:
        async def review(self, request, context):
            seen.append(request)
            return {"kind": "deny", "review": {**REVIEW, "outcome": "deny"}, "circuitBreakerTripped": False}

        def consumeGrant(self, request, session_id, token):
            return True

    result = asyncio.run(
        approve_domain_endpoint(
            {"hostname": "api.example.com", "port": 8443, "protocol": "tcp"},
            {**CONTEXT, "broker": _Capturing()},
        )
    )
    assert result["action"] == "deny"
    request = seen[0]
    assert request["source"] == "sandbox-runtime"
    assert request["surface"] == "network"
    assert request["operation"] == "connect"
    assert request["destination"] == "api.example.com:8443"
    assert request["command"] == "cat secret"
    assert request["cwd"] == "/repo"
    assert request["id"].startswith("sandbox-runtime-network-")
