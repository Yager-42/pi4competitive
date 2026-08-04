from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from competitive_app.adapter.out.sandbox.approval.sandbox import (
    sandbox_trap_to_boundary_request,
)
from competitive_app.adapter.out.sandbox import protocol
from competitive_app.adapter.out.sandbox.approved_registry import (
    ApprovedRegistryError,
    ApprovedToolRegistry,
    parse_approved_manifest,
)
from competitive_app.adapter.out.sandbox.protocol import (
    PROTOCOL_NAME,
    PROTOCOL_VERSION,
    RpcFrame,
    RpcProtocolError,
    decode_frame,
    decode_request,
    encode_frame,
    encode_request,
)
from competitive_app.adapter.out.sandbox.sandbox import Sandbox
from competitive_app.adapter.out.sandbox.sandbox_tool_executor import SandboxToolExecutor
from earendil_works.pi_agent import AgentTool, ToolExecutionTarget
from earendil_works.pi_agent.package_manager import load_capability_packages


CONTEXT = {"cwd": "/repo", "command": "tool", "agentName": "agent"}


def _filesystem(path: str) -> dict[str, Any]:
    return {
        "kind": "filesystem",
        "operation": "read",
        "path": path,
        "process": {"pid": 7},
    }


def test_sandbox_trap_fallback_ids_include_resource_and_kind_is_discriminated() -> None:
    first = sandbox_trap_to_boundary_request(_filesystem("/one"), CONTEXT)
    second = sandbox_trap_to_boundary_request(_filesystem("/two"), CONTEXT)
    network = sandbox_trap_to_boundary_request(
        {"kind": "network", "operation": "connect", "target": "one.example:443", "process": {"pid": 7}},
        CONTEXT,
    )
    assert first["id"] != second["id"]
    assert network["id"] != first["id"]
    assert network["destination"] == "one.example:443"


def test_sandbox_trap_rejects_invalid_operation_and_requested_path() -> None:
    with pytest.raises(ValueError, match="operation"):
        sandbox_trap_to_boundary_request({**_filesystem("/one"), "operation": "delete"}, CONTEXT)
    with pytest.raises(ValueError, match="requested_path"):
        sandbox_trap_to_boundary_request({**_filesystem("/one"), "requested_path": 7}, CONTEXT)
    with pytest.raises(ValueError, match="operation"):
        sandbox_trap_to_boundary_request(
            {"kind": "network", "operation": "read", "target": "one.example:443"}, CONTEXT
        )
    with pytest.raises(ValueError, match="unsupported sandbox trap kind"):
        sandbox_trap_to_boundary_request({"kind": "other", "operation": "read"}, CONTEXT)


def _manifest(identity: str) -> Any:
    return parse_approved_manifest(
        {
            "protocol": PROTOCOL_NAME,
            "protocolVersion": PROTOCOL_VERSION,
            "buildIdentity": identity,
            "tools": {"echo": {"module": __name__, "qualname": "_execute"}},
        }
    )


async def _execute(tool_call_id: str, params: dict[str, Any], signal: Any = None, on_update: Any = None) -> dict[str, Any]:
    return {"content": [], "details": params}

async def _executor_execute(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
) -> dict[str, Any]:
    return {"content": []}


def test_baked_manifest_build_identity_is_checked() -> None:
    registry = ApprovedToolRegistry.from_tools(
        [
            AgentTool(
                name="echo",
                description="echo",
                parameters={"type": "object"},
                label="echo",
                execute=_execute,
                executionTarget=ToolExecutionTarget(__name__, "_execute"),
            )
        ],
        allowed_module_prefixes=(__name__,),
    )
    registry.validate_baked_manifest(_manifest("build-1"), build_identity="build-1")
    with pytest.raises(ApprovedRegistryError, match="build identity mismatch"):
        registry.validate_baked_manifest(_manifest("build-2"), build_identity="build-1")

@pytest.mark.asyncio
async def test_registry_accepts_loader_capability_modules() -> None:
    capability_root = Path(__file__).resolve().parents[5] / "capability_packages"
    report = await load_capability_packages(
        capability_root,
        enabled=["echo_example"],
        cwd=capability_root,
        strict=True,
    )
    registry = ApprovedToolRegistry.from_tools(report.tools)
    assert "echo" in registry.bindings


def _request_mapping() -> dict[str, Any]:
    return {
        "protocolVersion": 1,


        "scopeId": "scope",
        "toolCallId": "call",
        "toolName": "echo",
        "target": {"module": "m", "qualname": "q"},
        "arguments": {},
    }


def test_encode_request_accepts_read_only_mapping() -> None:
    payload = encode_request(MappingProxyType(_request_mapping()))
    assert decode_request(payload).tool_name == "echo"


def test_decode_request_rejects_non_object_json_as_protocol_error() -> None:
    with pytest.raises(RpcProtocolError) as caught:
        decode_request(b"[]")
    assert caught.value.code == "invalid_shape"


def test_rpc_json_depth_and_frame_budgets_are_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    nested: Any = {}
    for _ in range(protocol.MAX_JSON_DEPTH + 2):
        nested = {"nested": nested}
    with pytest.raises(RpcProtocolError) as caught:
        decode_request(json.dumps({**_request_mapping(), "arguments": nested}).encode())
    assert caught.value.code == "payload_too_complex"

    error = RpcFrame(1, "scope", "call", 1, "error", error={
        "code": "failed", "safeMessage": "x" * (protocol.MAX_DIAGNOSTIC_BYTES + 1), "retryable": False,
    })
    with pytest.raises(RpcProtocolError, match="diagnostic"):
        encode_frame(error)

    monkeypatch.setattr(protocol, "MAX_FINAL_BYTES", 20)
    result = RpcFrame(1, "scope", "call", 1, "result", result={"content": [{"text": "x" * 40}]})
    with pytest.raises(RpcProtocolError, match="exceeds"):
        encode_frame(result)


class _MaskTranslator:
    def translate_command(self, command: str) -> str:
        return command

    def mask_output(self, output: str) -> str:
        return output.replace("secret", "masked")


class _Guard:
    def validate_command(self, command: str) -> None:
        return None


@pytest.mark.asyncio
async def test_sandbox_masks_returned_terminal_frame() -> None:
    terminal = RpcFrame(1, "scope", "call", 1, "result", result={"content": [{"text": "secret"}]})

    class Runtime:
        async def execute_worker(self, request: Any, on_frame: Any, *, command: str, signal: Any = None) -> RpcFrame:
            await on_frame(terminal)
            return terminal

        async def close(self) -> None:
            return None

    sandbox = Sandbox("scope", Runtime(), _MaskTranslator(), _Guard())
    returned = await sandbox.execute_worker(  # type: ignore[arg-type]
        type("Request", (), {"scope_id": "scope", "tool_call_id": "call"})(), lambda _frame: None
    )
    assert returned.result["content"][0]["text"] == "masked"  # type: ignore[index]


@pytest.mark.asyncio
async def test_executor_prefers_masked_terminal_delivered_through_callback() -> None:
    tool = AgentTool(
        name="echo",
        description="echo",
        parameters={"type": "object"},
        label="echo",
        execute=_executor_execute,
        executionTarget=ToolExecutionTarget(__name__, "_executor_execute"),
    )
    registry = ApprovedToolRegistry.from_tools([tool], allowed_module_prefixes=(__name__,))
    masked = RpcFrame(1, "scope", "call", 1, "result", result={"content": [{"text": "masked"}]})
    raw = RpcFrame(1, "scope", "call", 1, "result", result={"content": [{"text": "secret"}]})

    class SandboxDouble:
        async def execute_worker(self, request: Any, on_frame: Any, *, signal: Any = None) -> RpcFrame:
            await on_frame(masked)
            return raw

    class Provider:
        async def acquire(self, scope_id: str) -> SandboxDouble:
            return SandboxDouble()

    result = await SandboxToolExecutor(registry=registry, provider=Provider()).execute(
        scope_id="scope",
        tool=tool,
        tool_call_id="call",
        params={},
        signal=None,
        on_update=lambda _result: None,
    )
    assert result["content"][0]["text"] == "masked"
