"""Strict ``agent-tool-rpc.v1`` JSON request and frame codec.

NEW-HOST: no corresponding Poirot universal AgentTool bridge exists.  This
module is intentionally independent of Pi, FastAPI, Docker, and workflow
state so the same codec can run inside the minimal worker image.
"""
from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

PROTOCOL_NAME = "agent-tool-rpc.v1"
PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 5 * 1024 * 1024
MAX_FRAME_BYTES = 5 * 1024 * 1024
MAX_CUMULATIVE_UPDATE_BYTES = 5 * 1024 * 1024
MAX_FINAL_BYTES = 5 * 1024 * 1024
MAX_DIAGNOSTIC_BYTES = 10_000
MAX_JSON_DEPTH = 64
MAX_JSON_VALUES = 100_000

FrameType = Literal["update", "result", "error"]
_REQUEST_FIELDS = frozenset({"protocolVersion", "scopeId", "toolCallId", "toolName", "target", "arguments"})
_FRAME_FIELDS = frozenset({"protocolVersion", "scopeId", "toolCallId", "sequence", "type", "result", "error"})
_COMMON_FRAME_FIELDS = frozenset({"protocolVersion", "scopeId", "toolCallId", "sequence", "type"})


class RpcProtocolError(ValueError):
    """Raised when a request or frame violates the frozen RPC contract."""

    def __init__(self, message: str, *, code: str = "protocol_error") -> None:
        super().__init__(message)
        self.code = code


def _reject_constant(value: str) -> None:
    raise RpcProtocolError(f"non-finite JSON constant is forbidden: {value}", code="non_json_value")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RpcProtocolError(f"duplicate JSON object key: {key}", code="duplicate_key")
        result[key] = value
    return result


def _validate_json_value(
    value: Any,
    *,
    path: str = "$",
    depth: int = 0,
    budget: list[int] | None = None,
) -> None:
    if budget is None:
        budget = [0]
    budget[0] += 1
    if budget[0] > MAX_JSON_VALUES:
        raise RpcProtocolError("JSON value complexity exceeds limit", code="payload_too_complex")
    if depth > MAX_JSON_DEPTH:
        raise RpcProtocolError("JSON nesting exceeds limit", code="payload_too_complex")
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RpcProtocolError(f"non-finite number at {path}", code="non_json_value")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise RpcProtocolError(f"non-string object key at {path}", code="non_json_value")
            _validate_json_value(child, path=f"{path}.{key}", depth=depth + 1, budget=budget)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_json_value(child, path=f"{path}[{index}]", depth=depth + 1, budget=budget)
        return
    raise RpcProtocolError(f"unsupported JSON value at {path}: {type(value).__name__}", code="non_json_value")


def _json_bytes(value: Any, *, limit: int) -> bytes:
    _validate_json_value(value)
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RpcProtocolError("value is not JSON serializable", code="non_json_value") from exc
    if len(encoded) > limit:
        raise RpcProtocolError(f"JSON payload exceeds {limit} bytes", code="payload_too_large")
    return encoded


def _decode_json(payload: bytes | str, *, limit: int) -> Any:
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
    elif isinstance(payload, bytes):
        raw = payload
    else:
        raise RpcProtocolError("payload must be UTF-8 bytes or text", code="non_json_value")
    raw = raw.rstrip(b"\r\n")
    if len(raw) > limit:
        raise RpcProtocolError(f"JSON payload exceeds {limit} bytes", code="payload_too_large")
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
        _validate_json_value(value)
    except RpcProtocolError:
        raise
    except RecursionError as exc:
        raise RpcProtocolError("JSON nesting or complexity exceeds limit", code="payload_too_complex") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RpcProtocolError("invalid UTF-8 JSON payload", code="invalid_json") from exc
    return value


def _require_object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RpcProtocolError(f"{label} must be a JSON object", code="invalid_shape")
    return value


def _require_exact_fields(value: Mapping[str, Any], expected: frozenset[str], *, label: str) -> None:
    actual = set(value)
    missing = expected - actual
    unknown = actual - expected
    if missing:
        raise RpcProtocolError(f"{label} missing fields: {sorted(missing)}", code="invalid_fields")
    if unknown:
        raise RpcProtocolError(f"{label} has unknown fields: {sorted(unknown)}", code="unknown_fields")


def _require_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RpcProtocolError(f"{label} must be a non-empty string", code="invalid_identity")
    return value


def _require_version(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value != PROTOCOL_VERSION:
        raise RpcProtocolError("unsupported protocol version", code="protocol_mismatch")
    return value


def _require_target(value: Any) -> dict[str, str]:
    target = _require_object(value, label="target")
    _require_exact_fields(target, frozenset({"module", "qualname"}), label="target")
    return {
        "module": _require_string(target["module"], label="target.module"),
        "qualname": _require_string(target["qualname"], label="target.qualname"),
    }


def _validate_request(value: Any) -> dict[str, Any]:
    request = _require_object(value, label="request")
    _require_exact_fields(request, _REQUEST_FIELDS, label="request")
    return {
        "protocolVersion": _require_version(request["protocolVersion"]),
        "scopeId": _require_string(request["scopeId"], label="scopeId"),
        "toolCallId": _require_string(request["toolCallId"], label="toolCallId"),
        "toolName": _require_string(request["toolName"], label="toolName"),
        "target": _require_target(request["target"]),
        "arguments": request["arguments"],
    }


@dataclass(frozen=True, slots=True)
class RpcRequest:
    protocol_version: int
    scope_id: str
    tool_call_id: str
    tool_name: str
    target: dict[str, str]
    arguments: Any

    def to_mapping(self) -> dict[str, Any]:
        return {
            "protocolVersion": self.protocol_version,
            "scopeId": self.scope_id,
            "toolCallId": self.tool_call_id,
            "toolName": self.tool_name,
            "target": dict(self.target),
            "arguments": self.arguments,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "RpcRequest":
        request = _validate_request(value)
        return cls(
            protocol_version=request["protocolVersion"],
            scope_id=request["scopeId"],
            tool_call_id=request["toolCallId"],
            tool_name=request["toolName"],
            target=request["target"],
            arguments=request["arguments"],
        )


def encode_request(request: RpcRequest | Mapping[str, Any]) -> bytes:
    mapping = request.to_mapping() if isinstance(request, RpcRequest) else request
    return _json_bytes(_validate_request(mapping), limit=MAX_REQUEST_BYTES)


def decode_request(payload: bytes | str) -> RpcRequest:
    return RpcRequest.from_mapping(_decode_json(payload, limit=MAX_REQUEST_BYTES))


@dataclass(frozen=True, slots=True)
class RpcFrame:
    protocol_version: int
    scope_id: str
    tool_call_id: str
    sequence: int
    type: FrameType
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    @property
    def is_final(self) -> bool:
        return self.type in ("result", "error")

    def to_mapping(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "protocolVersion": self.protocol_version,
            "scopeId": self.scope_id,
            "toolCallId": self.tool_call_id,
            "sequence": self.sequence,
            "type": self.type,
        }
        if self.type == "error":
            value["error"] = self.error
        else:
            value["result"] = self.result
        return value


def _require_error(value: Any) -> dict[str, Any]:
    error = _require_object(value, label="error")
    _require_exact_fields(error, frozenset({"code", "safeMessage", "retryable"}), label="error")
    if not isinstance(error["retryable"], bool):
        raise RpcProtocolError("error.retryable must be boolean", code="invalid_shape")
    code = _require_string(error["code"], label="error.code")
    safe_message = _require_string(error["safeMessage"], label="error.safeMessage")
    try:
        diagnostic_size = len(safe_message.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise RpcProtocolError("error.safeMessage is not valid UTF-8", code="non_json_value") from exc
    if diagnostic_size > MAX_DIAGNOSTIC_BYTES:
        raise RpcProtocolError("error.safeMessage exceeds diagnostic limit", code="payload_too_large")
    return {
        "code": code,
        "safeMessage": safe_message,
        "retryable": error["retryable"],
    }


def _validate_frame(value: Any) -> RpcFrame:
    frame = _require_object(value, label="frame")
    if set(frame) - _FRAME_FIELDS:
        raise RpcProtocolError(
            f"frame has unknown fields: {sorted(set(frame) - _FRAME_FIELDS)}",
            code="unknown_fields",
        )
    if not _COMMON_FRAME_FIELDS.issubset(frame):
        raise RpcProtocolError("frame is missing required fields", code="invalid_fields")
    version = _require_version(frame["protocolVersion"])
    scope_id = _require_string(frame["scopeId"], label="scopeId")
    tool_call_id = _require_string(frame["toolCallId"], label="toolCallId")
    sequence = frame["sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise RpcProtocolError("frame.sequence must be a positive integer", code="invalid_sequence")
    frame_type = frame["type"]
    if frame_type not in ("update", "result", "error"):
        raise RpcProtocolError("frame.type is invalid", code="invalid_frame_type")
    if frame_type == "error":
        if "result" in frame:
            raise RpcProtocolError("error frame cannot contain result", code="invalid_fields")
        error = _require_error(frame.get("error"))
        return RpcFrame(version, scope_id, tool_call_id, sequence, "error", error=error)
    if "error" in frame:
        raise RpcProtocolError("result/update frame cannot contain error", code="invalid_fields")
    result = _require_object(frame.get("result"), label="result")
    if frame_type == "result":
        _json_bytes(result, limit=MAX_FINAL_BYTES)
    return RpcFrame(version, scope_id, tool_call_id, sequence, frame_type, result=result)  # type: ignore[arg-type]


def encode_frame(frame: RpcFrame | Mapping[str, Any]) -> bytes:
    mapping = frame.to_mapping() if isinstance(frame, RpcFrame) else dict(frame)
    validated = _validate_frame(mapping)
    return _json_bytes(validated.to_mapping(), limit=MAX_FRAME_BYTES)


def decode_frame(payload: bytes | str) -> RpcFrame:
    return _validate_frame(_decode_json(payload, limit=MAX_FRAME_BYTES))


@dataclass
class FrameSequence:
    """Enforce monotonic sequence and one-final-frame semantics."""

    next_sequence: int = 1
    final_seen: bool = False
    update_bytes: int = 0

    def accept(self, frame: RpcFrame, *, encoded_size: int | None = None) -> None:
        if self.final_seen:
            raise RpcProtocolError("frame arrived after terminal frame", code="late_frame")
        if frame.sequence != self.next_sequence:
            raise RpcProtocolError(
                f"expected sequence {self.next_sequence}, got {frame.sequence}",
                code="invalid_sequence",
            )
        size = encoded_size if encoded_size is not None else len(encode_frame(frame))
        if frame.type == "update":
            self.update_bytes += size
            if self.update_bytes > MAX_CUMULATIVE_UPDATE_BYTES:
                raise RpcProtocolError("cumulative update payload exceeds limit", code="payload_too_large")
        self.next_sequence += 1
        if frame.is_final:
            self.final_seen = True

    def finish(self) -> None:
        if not self.final_seen:
            raise RpcProtocolError("stream ended without a terminal frame", code="missing_final")


__all__ = [
    "FrameSequence",
    "MAX_CUMULATIVE_UPDATE_BYTES",
    "MAX_DIAGNOSTIC_BYTES",
    "MAX_FINAL_BYTES",
    "MAX_FRAME_BYTES",
    "MAX_JSON_DEPTH",
    "MAX_JSON_VALUES",
    "MAX_REQUEST_BYTES",
    "PROTOCOL_NAME",
    "PROTOCOL_VERSION",
    "RpcFrame",
    "RpcProtocolError",
    "RpcRequest",
    "decode_frame",
    "decode_request",
    "encode_frame",
    "encode_request",
]
