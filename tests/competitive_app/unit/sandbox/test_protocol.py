from __future__ import annotations

import math

import pytest

from competitive_app.adapter.out.sandbox.protocol import (
    FrameSequence,
    MAX_FRAME_BYTES,
    MAX_REQUEST_BYTES,
    RpcFrame,
    RpcProtocolError,
    RpcRequest,
    decode_frame,
    decode_request,
    encode_frame,
    encode_request,
)


def _request() -> RpcRequest:
    return RpcRequest(
        protocol_version=1,
        scope_id="scope",
        tool_call_id="call",
        tool_name="echo",
        target={"module": "capability_packages.echo_example.extensions.echo_tools", "qualname": "_echo_execute"},
        arguments={"text": "hello"},
    )


def test_request_roundtrip_is_strict_json() -> None:
    encoded = encode_request(_request())
    decoded = decode_request(encoded)
    assert decoded == _request()
    assert len(encoded) <= MAX_REQUEST_BYTES


def test_request_rejects_unknown_duplicate_and_non_json_values() -> None:
    with pytest.raises(RpcProtocolError, match="unknown fields"):
        decode_request(encode_request(_request())[:-1] + b',"extra":1}')
    with pytest.raises(RpcProtocolError, match="duplicate"):
        decode_request(b'{"protocolVersion":1,"protocolVersion":1,"scopeId":"s","toolCallId":"c","toolName":"t","target":{"module":"m","qualname":"q"},"arguments":{}}')
    with pytest.raises(RpcProtocolError, match="non-finite"):
        encode_request({**_request().to_mapping(), "arguments": {"value": math.nan}})
    with pytest.raises(RpcProtocolError, match="non-string"):
        encode_request({**_request().to_mapping(), "arguments": {1: "bad"}})


def test_frames_require_monotonic_sequence_and_one_final() -> None:
    update = RpcFrame(1, "scope", "call", 1, "update", result={"details": {"step": 1}})
    result = RpcFrame(1, "scope", "call", 2, "result", result={"content": []})
    sequence = FrameSequence()
    sequence.accept(decode_frame(encode_frame(update)))
    sequence.accept(decode_frame(encode_frame(result)))
    sequence.finish()
    with pytest.raises(RpcProtocolError, match="terminal"):
        sequence.accept(result)


def test_frames_reject_wrong_sequence_and_missing_final() -> None:
    sequence = FrameSequence()
    with pytest.raises(RpcProtocolError, match="expected sequence"):
        sequence.accept(RpcFrame(1, "scope", "call", 2, "result", result={}))
    with pytest.raises(RpcProtocolError, match="without a terminal"):
        FrameSequence().finish()


def test_frame_size_limit_is_measured_in_utf8_bytes() -> None:
    frame = RpcFrame(1, "scope", "call", 1, "result", result={"content": [{"text": "x" * MAX_FRAME_BYTES}]})
    with pytest.raises(RpcProtocolError, match="exceeds"):
        encode_frame(frame)
