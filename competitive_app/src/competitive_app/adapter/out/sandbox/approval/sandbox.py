"""App sandbox trap -> generic boundary request adapter (COPY-semantics).

Source: pi-auto-review@0.3.2 ``src/integrations/sandbox.ts``
Repository: erichll/pi-packages @ 10c8eeb8269ee478ff7383c7e6139301aa9665f9
License: MIT (retained under the native sandbox license directory)

Host delta: type-only; ``trap.process.pid``/``exe``/``cwd`` optional fields
behave exactly like the TS optional properties (undefined -> omitted).
"""
from __future__ import annotations

from earendil_works.pi_agent.boundary_approval import BoundaryRequest
from pi_auto_review.types import (
    SandboxBoundaryTrap,
    SandboxRequestContext,
)


def sandbox_trap_to_boundary_request(
    trap: SandboxBoundaryTrap,
    context: SandboxRequestContext,
) -> BoundaryRequest:
    process = trap.get("process") or {}
    process_suffix = (
        "" if process.get("pid") is None else f":{process['pid']}"
    )
    request_id = (
        f"sandbox-runtime:{trap['query_id']}"
        if trap.get("query_id")
        else f"sandbox-runtime:{trap['kind']}:{trap['operation']}{process_suffix}"
    )
    if trap["kind"] == "filesystem":
        return {
            "id": request_id,
            "source": "sandbox-runtime",
            "surface": (
                "filesystem-read"
                if trap["operation"] == "read"
                else "filesystem-write"
            ),
            "operation": trap["operation"],
            "cwd": process.get("cwd") or context.get("cwd", ""),
            "command": context.get("command"),
            "path": trap.get("requested_path") or trap["path"],
            "resolvedPath": trap["path"],
            "toolName": process.get("exe"),
            "agentName": context.get("agentName"),
            "matchedPolicy": {"decision": "ask", "rule": trap.get("reason")},
        }
    return {
        "id": request_id,
        "source": "sandbox-runtime",
        "surface": "network",
        "operation": trap["operation"],
        "cwd": process.get("cwd") or context.get("cwd", ""),
        "command": context.get("command"),
        "destination": trap["target"],
        "toolName": process.get("exe"),
        "agentName": context.get("agentName"),
        "matchedPolicy": {"decision": "ask"},
    }


__all__ = ["sandbox_trap_to_boundary_request"]
