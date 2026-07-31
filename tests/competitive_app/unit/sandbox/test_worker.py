from __future__ import annotations

import io
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from competitive_app.adapter.out.sandbox.protocol import (
    RpcRequest,
    decode_frame,
    encode_request,
)
from competitive_app.adapter.out.sandbox.worker import (
    BakedToolManifest,
    WorkerError,
    execute_request,
    run_worker,
)


async def _worker_tool(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any,
    on_update,
) -> dict[str, Any]:
    on_update({"details": {"partial": True}})
    return {"content": [{"type": "text", "text": str(params["text"])}], "details": {}}


async def _failing_tool(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any,
    on_update,
) -> dict[str, Any]:
    raise RuntimeError("secret traceback should not cross the boundary")


def _install_fixture_module() -> str:
    module = types.ModuleType("worker_fixture")
    module._worker_tool = _worker_tool
    module._failing_tool = _failing_tool
    sys.modules[module.__name__] = module
    return module.__name__


def _manifest(module: str, qualname: str) -> BakedToolManifest:
    return BakedToolManifest(
        protocol="agent-tool-rpc.v1",
        protocol_version=1,
        build_identity="build-1",
        tools={"echo": {"module": module, "qualname": qualname}},
    )


def _request(module: str, qualname: str = "_worker_tool") -> RpcRequest:
    return RpcRequest(
        protocol_version=1,
        scope_id="scope",
        tool_call_id="call",
        tool_name="echo",
        target={"module": module, "qualname": qualname},
        arguments={"text": "ok"},
    )


@pytest.mark.asyncio
async def test_worker_emits_ordered_update_and_final_result() -> None:
    module = _install_fixture_module()
    encoded: list[bytes] = []
    await execute_request(_request(module), _manifest(module, "_worker_tool"), encoded.append)
    frames = [decode_frame(value) for value in encoded]
    assert [frame.type for frame in frames] == ["update", "result"]
    assert [frame.sequence for frame in frames] == [1, 2]
    assert frames[-1].result["content"][0]["text"] == "ok"  # type: ignore[index]


@pytest.mark.asyncio
async def test_worker_maps_execution_errors_without_raw_details() -> None:
    module = _install_fixture_module()
    encoded: list[bytes] = []
    with pytest.raises(WorkerError, match="tool execution failed"):
        await execute_request(
            _request(module, "_failing_tool"),
            _manifest(module, "_failing_tool"),
            encoded.append,
        )
    frame = decode_frame(encoded[-1])
    assert frame.type == "error"
    assert frame.error == {
        "code": "tool_execution_error",
        "safeMessage": "tool execution failed",
        "retryable": False,
    }


def test_worker_reads_one_request_and_emits_jsonl(tmp_path: Path) -> None:
    module = _install_fixture_module()
    manifest_path = tmp_path / "approved_tools.json"
    manifest_path.write_text(
        json.dumps(
            {
                "protocol": "agent-tool-rpc.v1",
                "protocolVersion": 1,
                "buildIdentity": "build-1",
                "tools": {"echo": {"module": module, "qualname": "_worker_tool"}},
            }
        ),
        encoding="utf-8",
    )
    request = encode_request(_request(module))
    output = io.BytesIO()
    code = run_worker(
        manifest_path=manifest_path,
        stdin=io.BytesIO(request + b"\nignored\n"),
        stdout=output,
    )
    frames = [decode_frame(line) for line in output.getvalue().splitlines()]
    assert code == 0
    assert len(frames) == 2
