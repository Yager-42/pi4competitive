from __future__ import annotations

from typing import Any

import pytest

from competitive_app.adapter.out.sandbox.approved_registry import (
    ApprovedRegistryError,
    ApprovedToolRegistry,
    parse_approved_manifest,
)
from competitive_app.adapter.out.sandbox.protocol import PROTOCOL_NAME, PROTOCOL_VERSION
from earendil_works.pi_agent import AgentTool, ToolExecutionTarget


async def _echo(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
) -> dict[str, Any]:
    return {"content": [], "details": params}


async def _other(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
) -> dict[str, Any]:
    return {"content": [], "details": params}


def _tool(name: str, execute: Any = _echo) -> AgentTool:
    return AgentTool(
        name=name,
        description=name,
        parameters={"type": "object"},
        label=name,
        execute=execute,
        executionTarget=ToolExecutionTarget(__name__, execute.__name__),
    )


def test_registry_rejects_missing_rebound_and_collision_targets() -> None:
    registry = ApprovedToolRegistry.from_tools([_tool("echo"), _tool("other", _other)], allowed_module_prefixes=(__name__,))
    assert registry.target_for("echo").qualname == "_echo"
    registry.binding_for(_tool("echo"))

    with pytest.raises(ApprovedRegistryError, match="no execution target"):
        ApprovedToolRegistry.from_tools(
            [AgentTool("missing", "missing", {}, "Missing", _echo)]
        )
    with pytest.raises(ApprovedRegistryError, match="rebound"):
        registry.binding_for(
            AgentTool(
                "echo",
                "echo",
                {},
                "Echo",
                _other,
                executionTarget=ToolExecutionTarget(__name__, "_other"),
            )
        )
    with pytest.raises(ApprovedRegistryError, match="collision"):
        ApprovedToolRegistry.from_tools([_tool("echo"), _tool("duplicate", _echo)], allowed_module_prefixes=(__name__,))


def test_registry_host_set_must_be_subset_of_baked_manifest() -> None:
    registry = ApprovedToolRegistry.from_tools([_tool("echo")], allowed_module_prefixes=(__name__,))
    manifest = parse_approved_manifest(
        {
            "protocol": PROTOCOL_NAME,
            "protocolVersion": PROTOCOL_VERSION,
            "buildIdentity": "image-build",
            "tools": {
                "echo": {"module": __name__, "qualname": "_echo"},
                "unused": {"module": __name__, "qualname": "_other"},
            },
        }
    )
    registry.validate_baked_manifest(manifest)

    bad = parse_approved_manifest(
        {
            "protocol": PROTOCOL_NAME,
            "protocolVersion": PROTOCOL_VERSION,
            "buildIdentity": "image-build",
            "tools": {"echo": {"module": __name__, "qualname": "_other"}},
        }
    )
    with pytest.raises(ApprovedRegistryError, match="target mismatch"):
        registry.validate_baked_manifest(bad)
