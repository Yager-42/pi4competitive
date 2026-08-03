"""JournalStream unit tests — llm.request/llm.response at the stream_fn choke point.

Host addition (non-copied): the pi_agent port's agent loop never fires
before_provider_request/after_provider_response, so llm.* events are produced
here (packages/agent zero-diff). Assertions: request-before-response ordering,
status mapping (ok/error), error delivery never raises, passthrough of events.
"""
from __future__ import annotations

from competitive_app.application.model.journal_stream import JournalStream
from earendil_works.pi_ai.types import (
    AssistantMessageEvent,
    Context,
    Model,
    empty_usage,
)
from earendil_works.pi_ai.utils.event_stream import AssistantMessageEventStream


def _chain_model(provider: str) -> Model:
    return {
        "id": f"m-{provider}", "name": f"m-{provider}", "api": "openai-completions",
        "provider": provider, "baseUrl": "http://localhost:0", "reasoning": False,
        "input": ["text"], "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 8, "maxTokens": 8,
    }


def _ok_message(model: Model, text: str = "ok") -> dict:
    return {
        "role": "assistant", "content": [{"type": "text", "text": text}],
        "api": "a", "provider": model["provider"], "model": model["id"],
        "usage": empty_usage(), "stopReason": "stop", "timestamp": 0,
    }


def _error_message(model: Model) -> dict:
    return {
        "role": "assistant", "content": [], "api": "a", "provider": model["provider"],
        "model": model["id"], "usage": empty_usage(), "stopReason": "error",
        "errorMessage": "boom", "error": {"type": "http_error", "statusCode": 429, "message": "boom"},
    }


def _stream(*events: AssistantMessageEvent) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()
    for event in events:
        stream.push(event)
    return stream


async def _collect(stream: AssistantMessageEventStream) -> tuple[list[str], dict]:
    events = [e async for e in stream]
    result = await stream.result()
    return [e["type"] for e in events], result


MODEL = _chain_model("alpha")
CTX: Context = {"messages": [{"role": "user", "content": "hi", "timestamp": 0}]}


async def test_request_before_response_and_ok_status() -> None:
    inner = _stream({"type": "done", "reason": "stop", "message": _ok_message(MODEL)})
    logs: list[tuple[str, dict]] = []

    def stream_fn(model: Model, context: Context, options: object | None = None):
        assert model["id"] == "m-alpha"
        return inner

    wrapped = JournalStream(stream_fn, lambda t, p: logs.append((t, p)))
    stream = wrapped(MODEL, CTX, None)
    types, result = await _collect(stream)
    assert types[-1] == "done"
    assert result["stopReason"] == "stop"
    assert logs[0][0] == "llm.request"
    assert logs[0][1] == {"model": "m-alpha", "provider": "alpha"}
    assert logs[1][0] == "llm.response"
    assert logs[1][1]["status"] == "ok"
    assert logs[1][1]["errorType"] is None


async def test_error_stream_maps_error_status_without_raising() -> None:
    message = _error_message(MODEL)
    inner = _stream({"type": "error", "reason": "error", "error": message})
    logs: list[tuple[str, dict]] = []

    def stream_fn(model: Model, context: Context, options: object | None = None):
        return inner

    wrapped = JournalStream(stream_fn, lambda t, p: logs.append((t, p)))
    stream = wrapped(MODEL, CTX, None)
    _, result = await _collect(stream)
    assert result["stopReason"] == "error"
    assert result["error"]["statusCode"] == 429
    response = logs[1][1]
    assert response["status"] == "error"
    assert response["errorType"] == "http_error"


async def test_raising_stream_fn_delivers_error_message() -> None:
    logs: list[tuple[str, dict]] = []

    def stream_fn(model: Model, context: Context, options: object | None = None):
        raise RuntimeError("kaboom")

    wrapped = JournalStream(stream_fn, lambda t, p: logs.append((t, p)))
    stream = wrapped(MODEL, CTX, None)
    types, result = await _collect(stream)
    assert types[-1] == "error"
    assert result["stopReason"] == "error"
    assert logs[1][0] == "llm.response"
    assert logs[1][1]["status"] == "error"
    assert logs[1][1]["errorType"] == "other"


async def test_passthrough_preserves_intermediate_events() -> None:
    message = _ok_message(MODEL, "hello world")
    inner = _stream(
        {"type": "start", "partial": {**message, "content": []}},
        {"type": "text_start", "contentIndex": 0, "partial": {**message, "content": [{"type": "text", "text": ""}]}},
        {"type": "text_delta", "contentIndex": 0, "delta": "hello", "partial": message},
        {"type": "done", "reason": "stop", "message": message},
    )
    logs: list[tuple[str, dict]] = []

    def stream_fn(model: Model, context: Context, options: object | None = None):
        return inner

    wrapped = JournalStream(stream_fn, lambda t, p: logs.append((t, p)))
    stream = wrapped(MODEL, CTX, None)
    types, result = await _collect(stream)
    assert types == ["start", "text_start", "text_delta", "done"]
    assert result["content"][0]["text"] == "hello world"
