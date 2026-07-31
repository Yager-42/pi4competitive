"""Minimal one-request AgentTool worker for the derived image.

NEW-HOST: Poirot has no universal arbitrary-AgentTool worker bridge.  The
worker imports only an approved module-level coroutine, executes one request,
and emits protocol frames; it does not import FastAPI, Pi Agent, LLM, session,
or workflow control-plane code.
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .protocol import (
    FrameSequence,
    PROTOCOL_NAME,
    PROTOCOL_VERSION,
    RpcFrame,
    RpcProtocolError,
    RpcRequest,
    decode_request,
    encode_frame,
)

DEFAULT_MANIFEST_PATH = "/opt/pi4competitive/approved_tools.json"


class WorkerError(RuntimeError):
    def __init__(self, code: str, safe_message: str, *, retryable: bool = False) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class BakedToolManifest:
    protocol: str
    protocol_version: int
    build_identity: str
    tools: Mapping[str, Mapping[str, str]]


def _strict_json(raw: bytes) -> Any:
    def reject_constant(value: str) -> None:
        raise WorkerError("manifest_invalid", f"manifest contains {value}")

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            if key in value:
                raise WorkerError("manifest_invalid", "manifest contains duplicate keys")
            value[key] = child
        return value

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
        )
    except WorkerError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerError("manifest_invalid", "approved tool manifest is invalid") from exc


def load_baked_manifest(path: str | Path = DEFAULT_MANIFEST_PATH) -> BakedToolManifest:
    try:
        value = _strict_json(Path(path).read_bytes())
    except OSError as exc:
        raise WorkerError("manifest_unavailable", "approved tool manifest is unavailable") from exc
    if not isinstance(value, dict):
        raise WorkerError("manifest_invalid", "approved tool manifest is not an object")
    if set(value) != {"protocol", "protocolVersion", "buildIdentity", "tools"}:
        raise WorkerError("manifest_invalid", "approved tool manifest fields are invalid")
    if value["protocol"] != PROTOCOL_NAME or value["protocolVersion"] != PROTOCOL_VERSION:
        raise WorkerError("protocol_mismatch", "approved tool manifest protocol mismatch")
    if not isinstance(value["buildIdentity"], str) or not value["buildIdentity"]:
        raise WorkerError("manifest_invalid", "approved tool manifest build identity is invalid")
    tools = value["tools"]
    if not isinstance(tools, dict) or not tools:
        raise WorkerError("manifest_invalid", "approved tool manifest has no tools")
    normalized: dict[str, Mapping[str, str]] = {}
    targets: set[tuple[str, str]] = set()
    for name, target in tools.items():
        if not isinstance(name, str) or not name:
            raise WorkerError("manifest_invalid", "approved tool name is invalid")
        if not isinstance(target, dict) or set(target) != {"module", "qualname"}:
            raise WorkerError("manifest_invalid", "approved tool target is invalid")
        module, qualname = target["module"], target["qualname"]
        if not isinstance(module, str) or not module or not isinstance(qualname, str) or not qualname:
            raise WorkerError("manifest_invalid", "approved tool target identity is invalid")
        identity = (module, qualname)
        if identity in targets:
            raise WorkerError("manifest_invalid", "approved tool target collision")
        targets.add(identity)
        normalized[name] = {"module": module, "qualname": qualname}
    return BakedToolManifest(
        protocol=value["protocol"],
        protocol_version=value["protocolVersion"],
        build_identity=value["buildIdentity"],
        tools=normalized,
    )


class WorkerAbortSignal:
    """Worker-local four-argument signal; no host object crosses RPC."""

    def __init__(self) -> None:
        self.aborted = False
        self._listeners: list[Callable[[], None]] = []

    def add_event_listener(self, _type: str, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def abort(self) -> None:
        if self.aborted:
            return
        self.aborted = True
        for callback in list(self._listeners):
            callback()


def _safe_protocol_error(error: RpcProtocolError) -> WorkerError:
    messages = {
        "protocol_mismatch": "worker protocol mismatch",
        "payload_too_large": "tool payload exceeds the worker limit",
        "invalid_json": "tool request is not valid JSON",
        "non_json_value": "tool payload is not JSON-compatible",
    }
    return WorkerError(error.code, messages.get(error.code, "tool request is invalid"))


def _resolve_target(request: RpcRequest, manifest: BakedToolManifest) -> Callable[..., Any]:
    baked = manifest.tools.get(request.tool_name)
    if baked is None:
        raise WorkerError("target_not_approved", "tool target is not approved")
    if baked["module"] != request.target["module"] or baked["qualname"] != request.target["qualname"]:
        raise WorkerError("target_mismatch", "tool target does not match the worker manifest")
    if "<locals>" in request.target["qualname"] or "." in request.target["qualname"]:
        raise WorkerError("target_invalid", "tool target is not a module-level callable")
    try:
        module = importlib.import_module(request.target["module"])
        target = getattr(module, request.target["qualname"])
    except (ImportError, AttributeError) as exc:
        raise WorkerError("target_not_importable", "approved tool target cannot be imported") from exc
    if not inspect.isfunction(target) or not inspect.iscoroutinefunction(target):
        raise WorkerError("target_invalid", "approved target is not an async function")
    try:
        parameters = tuple(inspect.signature(target).parameters.values())
    except (TypeError, ValueError) as exc:
        raise WorkerError("target_invalid", "approved target signature is unavailable") from exc
    if len(parameters) != 4 or any(
        parameter.kind not in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        for parameter in parameters
    ):
        raise WorkerError("target_invalid", "approved target must accept four positional arguments")
    return target


async def execute_request(
    request: RpcRequest,
    manifest: BakedToolManifest,
    emit: Callable[[bytes], None],
) -> None:
    sequence = FrameSequence()
    signal = WorkerAbortSignal()

    def emit_frame(frame: RpcFrame) -> None:
        encoded = encode_frame(frame)
        sequence.accept(frame, encoded_size=len(encoded))
        emit(encoded)

    def on_update(partial_result: Any) -> None:
        if sequence.final_seen:
            return
        if not isinstance(partial_result, dict):
            raise WorkerError("non_json_result", "tool update is not a JSON object")
        emit_frame(
            RpcFrame(
                protocol_version=PROTOCOL_VERSION,
                scope_id=request.scope_id,
                tool_call_id=request.tool_call_id,
                sequence=sequence.next_sequence,
                type="update",
                result=partial_result,
            )
        )

    try:
        target = _resolve_target(request, manifest)
        result = await target(request.tool_call_id, request.arguments, signal, on_update)
        if not isinstance(result, dict):
            raise WorkerError("non_json_result", "tool result is not a JSON object")
        emit_frame(
            RpcFrame(
                protocol_version=PROTOCOL_VERSION,
                scope_id=request.scope_id,
                tool_call_id=request.tool_call_id,
                sequence=sequence.next_sequence,
                type="result",
                result=result,
            )
        )
        sequence.finish()
    except WorkerError as error:
        if not sequence.final_seen:
            emit_frame(
                RpcFrame(
                    protocol_version=PROTOCOL_VERSION,
                    scope_id=request.scope_id,
                    tool_call_id=request.tool_call_id,
                    sequence=sequence.next_sequence,
                    type="error",
                    error={
                        "code": error.code,
                        "safeMessage": error.safe_message,
                        "retryable": error.retryable,
                    },
                )
            )
        raise
    except RpcProtocolError as error:
        worker_error = _safe_protocol_error(error)
        if not sequence.final_seen:
            emit_frame(
                RpcFrame(
                    protocol_version=PROTOCOL_VERSION,
                    scope_id=request.scope_id,
                    tool_call_id=request.tool_call_id,
                    sequence=sequence.next_sequence,
                    type="error",
                    error={
                        "code": worker_error.code,
                        "safeMessage": worker_error.safe_message,
                        "retryable": worker_error.retryable,
                    },
                )
            )
        raise worker_error from error
    except Exception as exc:  # noqa: BLE001
        if not sequence.final_seen:
            emit_frame(
                RpcFrame(
                    protocol_version=PROTOCOL_VERSION,
                    scope_id=request.scope_id,
                    tool_call_id=request.tool_call_id,
                    sequence=sequence.next_sequence,
                    type="error",
                    error={
                        "code": "tool_execution_error",
                        "safeMessage": "tool execution failed",
                        "retryable": False,
                    },
                )
            )
        raise WorkerError("tool_execution_error", "tool execution failed") from exc


def run_worker(
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    stdin: Any = None,
    stdout: Any = None,
) -> int:
    """Read exactly one request line and emit only protocol frames to stdout."""

    input_stream = stdin or sys.stdin.buffer
    output_stream = stdout or sys.stdout.buffer
    line = input_stream.readline()
    if not line:
        return 2
    try:
        request = decode_request(line)
        manifest = load_baked_manifest(manifest_path)

        def write_frame(encoded: bytes) -> None:
            output_stream.write(encoded + b"\n")
            output_stream.flush()

        asyncio.run(
            execute_request(
                request,
                manifest,
                write_frame,
            )
        )
    except (RpcProtocolError, WorkerError):
        return 1
    return 0


def main() -> None:
    raise SystemExit(run_worker())


if __name__ == "__main__":
    main()


__all__ = [
    "BakedToolManifest",
    "DEFAULT_MANIFEST_PATH",
    "WorkerAbortSignal",
    "WorkerError",
    "execute_request",
    "load_baked_manifest",
    "main",
    "run_worker",
]
