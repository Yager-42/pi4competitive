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
    process_suffix = "" if process.get("pid") is None else f":{process['pid']}"
    kind = trap.get("kind")
    if kind not in ("filesystem", "network"):
        raise ValueError(f"unsupported sandbox trap kind: {kind!r}")
    operation = trap.get("operation")
    if not isinstance(operation, str) or not operation:
        raise ValueError("sandbox trap operation must be a non-empty string")
    allowed_operations = {"read", "write"} if kind == "filesystem" else {"connect", "bind"}
    if operation not in allowed_operations:
        raise ValueError(f"unsupported sandbox {kind} trap operation: {operation!r}")
    if kind == "filesystem":
        resolved_path = trap.get("path")
        if not isinstance(resolved_path, str) or not resolved_path:
            raise ValueError("sandbox filesystem trap path is missing")
        requested_path = trap.get("requested_path")
        if requested_path is not None and (not isinstance(requested_path, str) or not requested_path):
            raise ValueError("sandbox filesystem trap requested_path must be a non-empty string")
        resource = f"{requested_path}:{resolved_path}" if requested_path else resolved_path
    else:
        resource = trap.get("target")
    if not isinstance(resource, str) or not resource:
        raise ValueError(f"sandbox {kind} trap resource is missing")
    request_id = (
        f"sandbox-runtime:{trap['query_id']}"
        if trap.get("query_id")
        else f"sandbox-runtime:{kind}:{operation}:{resource}{process_suffix}"
    )
    if kind == "filesystem":
        return {
            "id": request_id,
            "source": "sandbox-runtime",
            "surface": (
                "filesystem-read"
                if operation == "read"
                else "filesystem-write"
            ),
            "operation": operation,
            "cwd": process.get("cwd") or context.get("cwd", ""),
            "command": context.get("command"),
            "path": trap.get("requested_path") or resolved_path,
            "resolvedPath": resolved_path,
            "toolName": process.get("exe"),
            "agentName": context.get("agentName"),
            "matchedPolicy": {"decision": "ask", "rule": trap.get("reason")},
        }
    if kind == "network":
        return {
            "id": request_id,
            "source": "sandbox-runtime",
            "surface": "network",
            "operation": operation,
            "cwd": process.get("cwd") or context.get("cwd", ""),
            "command": context.get("command"),
            "destination": resource,
            "toolName": process.get("exe"),
            "agentName": context.get("agentName"),
            "matchedPolicy": {"decision": "ask"},
        }
    raise AssertionError("unreachable sandbox trap kind")


__all__ = ["sandbox_trap_to_boundary_request"]
