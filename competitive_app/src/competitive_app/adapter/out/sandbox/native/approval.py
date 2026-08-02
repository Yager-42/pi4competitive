"""Sandbox trap/endpoint approval via the boundary broker (ADAPT).

Source: pi-sandbox@0.4.2 ``src/approval.ts``
Repository: erichll/pi-packages @ 10c8eeb8269ee478ff7383c7e6139301aa9665f9
License: Apache-2.0 (retained under the native sandbox license directory)

Host delta:
- ``approveHostIPCExecution`` is OMITTED with its trigger type (host-ipc.ts
  is out of scope per G0 §2.1: no Host IPC symbol/config/path may exist —
  a negative contract test asserts absence).
- Python async/dict form; ``signal`` abort uses an ``asyncio.Future``
  (caller-owned) matching the executor's abort signal.
- ``randomUUID()`` -> ``uuid.uuid4()``.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Awaitable, Callable, Literal, NotRequired, TypedDict

from earendil_works.pi_agent.boundary_approval import BoundaryRequest

from pi_auto_review.types import SandboxBoundaryTrap

from ..approval.sandbox import sandbox_trap_to_boundary_request
from .traps import SandboxApprovalAction


class NetworkEndpoint(TypedDict):
    hostname: str
    port: int
    protocol: str  # literal "http" | "https" | "tcp"


HumanApproval = Callable[
    [BoundaryRequest, str | None, asyncio.Future | None],
    Awaitable[Literal["allow-once", "deny"]],
]


class TrapApprovalContext(TypedDict):
    command: str
    cwd: str
    sessionId: str
    scopeKey: str
    agentName: NotRequired[str]
    signal: NotRequired[asyncio.Future]
    humanApproval: NotRequired[HumanApproval]
    broker: NotRequired[BoundaryApprovalBrokerService]


class TrapApprovalResult(TypedDict):
    action: SandboxApprovalAction
    source: str  # "hard-deny" | "reviewer" | "human" | "unavailable" | "invalid-grant"
    reason: NotRequired[str]


async def approve_domain_endpoint(
    endpoint: NetworkEndpoint,
    context: TrapApprovalContext,
) -> TrapApprovalResult:
    """Review a network endpoint the sandbox proxy wants to connect to."""
    request: BoundaryRequest = {
        "id": f"sandbox-runtime-network-{uuid.uuid4()}",
        "source": "sandbox-runtime",
        "surface": "network",
        "operation": "connect",
        "cwd": context["cwd"],
        "command": context["command"],
        "destination": f"{endpoint['hostname']}:{endpoint['port']}",
        "agentName": context.get("agentName"),
    }
    return await _approve_boundary_request(request, context)


async def _ask_human(
    request: BoundaryRequest,
    context: TrapApprovalContext,
    reason: str | None = None,
) -> TrapApprovalResult:
    human_approval = context.get("humanApproval")
    signal = context.get("signal")
    if human_approval is None or (signal is not None and signal.done()):
        return {"action": "deny", "source": "unavailable", "reason": reason}
    choice = await human_approval(request, reason, signal)
    return (
        {"action": "allow", "source": "human", "reason": reason}
        if choice == "allow-once"
        else {"action": "deny", "source": "human", "reason": reason}
    )


async def _approve_boundary_request(
    request: BoundaryRequest,
    context: TrapApprovalContext,
) -> TrapApprovalResult:
    broker = context.get("broker")
    if broker is None:
        return await _ask_human(
            request, context, "pi-auto-review broker is unavailable"
        )

    try:
        decision = await broker.review(
            request,
            {
                "sessionId": context["sessionId"],
                "scopeKey": context["scopeKey"],
                "issueGrant": True,
            },
        )
    except Exception as error:
        return {
            "action": "deny",
            "source": "unavailable",
            "reason": f"Broker failed: {error}",
        }

    if decision["kind"] == "deny":
        return {
            "action": "deny",
            "source": "reviewer",
            "reason": decision["review"]["rationale"],
        }
    if decision["kind"] == "defer":
        return await _ask_human(request, context, decision["review"]["rationale"])
    if not decision.get("grant") or not broker.consumeGrant(
        request, context["sessionId"], decision["grant"]["token"]
    ):
        return {
            "action": "deny",
            "source": "invalid-grant",
            "reason": "The exact one-shot grant is missing, invalid, or expired.",
        }
    return {
        "action": "allow",
        "source": "reviewer",
        "reason": decision["review"]["rationale"],
    }


async def approve_sandbox_trap(
    trap: SandboxBoundaryTrap,
    context: TrapApprovalContext,
) -> TrapApprovalResult:
    """Approve a sandbox enforcement trap. Network traps and explicit
    deny-match filesystem traps are hard-denied without a broker round
    trip; everything else goes through the boundary broker."""
    if trap["kind"] == "network":
        return {
            "action": "deny",
            "source": "hard-deny",
            "reason": (
                "Direct network access is disabled; use the authenticated "
                "domain proxy."
            ),
        }
    if trap["kind"] == "filesystem" and trap.get("reason") == "deny_match":
        return {
            "action": "deny",
            "source": "hard-deny",
            "reason": "The path matches an explicit sandbox deny rule.",
        }
    request = sandbox_trap_to_boundary_request(
        trap,
        {
            "command": context["command"],
            "cwd": context["cwd"],
            "agentName": context.get("agentName"),
        },
    )
    return await _approve_boundary_request(request, context)


__all__ = [
    "HumanApproval",
    "NetworkEndpoint",
    "TrapApprovalContext",
    "TrapApprovalResult",
    "approve_domain_endpoint",
    "approve_sandbox_trap",
]
