"""O5 — trap formatting + boundary-request mapping vectors (PORT of
pi-sandbox traps.test.ts and pi-auto-review sandbox.test.ts).

Source: pi-sandbox@0.4.2 ``traps.test.ts`` / pi-auto-review@0.3.2
``test/sandbox.test.ts``
License: Apache-2.0 + MIT (retained under the native sandbox license directory)
"""
from __future__ import annotations

from competitive_app.adapter.out.sandbox.approval.sandbox import (
    sandbox_trap_to_boundary_request,
)
from competitive_app.adapter.out.sandbox.native.traps import (
    SandboxApprovalTrap,
    format_sandbox_trap,
)


def test_formats_filesystem_and_network_sandbox_boundaries() -> None:
    assert (
        format_sandbox_trap(
            {
                "kind": "filesystem",
                "operation": "read",
                "path": "/home/user/secret",
            }
        )
        == "read /home/user/secret"
    )
    assert (
        format_sandbox_trap(
            {"kind": "network", "operation": "connect", "target": "api.example.com:443"}
        )
        == "connect api.example.com:443"
    )


def test_maps_filesystem_boundary_without_losing_resolved_path() -> None:
    request = sandbox_trap_to_boundary_request(
        {
            "kind": "filesystem",
            "query_id": "42",
            "operation": "read",
            "path": "/repo/secret",
            "requested_path": "./secret",
            "reason": "allow_miss",
            "process": {"pid": 7, "exe": "/usr/bin/cat", "cwd": "/repo"},
        },
        {"cwd": "/fallback", "command": "cat ./secret"},
    )
    assert request == {
        "id": "sandbox-runtime:42",
        "source": "sandbox-runtime",
        "surface": "filesystem-read",
        "operation": "read",
        "cwd": "/repo",
        "command": "cat ./secret",
        "path": "./secret",
        "resolvedPath": "/repo/secret",
        "toolName": "/usr/bin/cat",
        "agentName": None,
        "matchedPolicy": {"decision": "ask", "rule": "allow_miss"},
    }


def test_maps_network_boundary_to_exact_destination() -> None:
    request = sandbox_trap_to_boundary_request(
        {"kind": "network", "operation": "connect", "target": "api.example.com:443"},
        {"cwd": "/repo"},
    )
    assert request["source"] == "sandbox-runtime"
    assert request["surface"] == "network"
    assert request["destination"] == "api.example.com:443"
    assert request["cwd"] == "/repo"


def test_write_operation_surface_and_auto_ids() -> None:
    request = sandbox_trap_to_boundary_request(
        {"kind": "filesystem", "operation": "write", "path": "/repo/out"},
        {"cwd": "/repo"},
    )
    assert request["surface"] == "filesystem-write"
    assert request["id"] == "sandbox-runtime:filesystem:write"

    request2 = sandbox_trap_to_boundary_request(
        {
            "kind": "filesystem",
            "operation": "write",
            "path": "/repo/out",
            "process": {"pid": 12},
        },
        {"cwd": "/repo"},
    )
    assert request2["id"] == "sandbox-runtime:filesystem:write:12"


def test_fallback_cwd_and_agent_name() -> None:
    request = sandbox_trap_to_boundary_request(
        {"kind": "network", "operation": "connect", "target": "x:1"},
        {"cwd": "/fallback", "agentName": "pi"},
    )
    assert request["cwd"] == "/fallback"
    assert request["agentName"] == "pi"


def test_trap_alias_covers_both_kinds() -> None:
    traps: list[SandboxApprovalTrap] = [
        {"kind": "filesystem", "operation": "read", "path": "/x"},
        {"kind": "network", "operation": "bind", "target": "127.0.0.1:9000"},
    ]
    assert len(traps) == 2
