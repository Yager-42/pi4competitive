from __future__ import annotations

import asyncio
import json
import threading

import pytest

from earendil_works.pi_ai.api import anthropic_messages
from earendil_works.pi_ai.api import azure_openai_responses_lazy, bedrock_converse_stream_lazy
from earendil_works.pi_ai.api import google_shared, openai_codex_responses_lazy, openai_responses_lazy
from earendil_works.pi_ai.api import openai_completions
from earendil_works.pi_ai.api._http_stream import error_message, stream_openai_chat_completions
from earendil_works.pi_ai.api.lazy import forward_stream, lazy_stream
from earendil_works.pi_ai.api.transform_messages import (
    context_to_anthropic_messages,
    context_to_openai_messages,
)
from earendil_works.pi_ai.utils.event_stream import create_assistant_message_event_stream

MODEL = {"id": "m", "api": "openai-completions", "provider": "p", "baseUrl": "https://example.test"}
ANTHROPIC_MODEL = {"id": "m", "api": "anthropic-messages", "provider": "p", "baseUrl": "https://example.test"}


@pytest.mark.asyncio
async def test_anthropic_payload_callback_failure_closes_stream() -> None:
    def fail(_payload, _model):
        raise ValueError("payload failed")

    result = anthropic_messages.stream(ANTHROPIC_MODEL, {"messages": []}, {"apiKey": "x", "onPayload": fail})
    message = await result.result()
    assert message["stopReason"] == "error"
    assert "payload failed" in message["errorMessage"]


def test_google_preserves_tool_results_and_calls() -> None:
    context = {
        "messages": [
            {"role": "assistant", "content": [{"type": "toolCall", "name": "lookup", "id": "1", "arguments": {"q": "x"}}]},
            {"role": "toolResult", "toolCallId": "1", "toolName": "lookup", "content": [{"type": "text", "text": "answer"}], "isError": False},
        ]
    }
    contents = google_shared.context_to_google_contents(context)
    assert contents[0]["parts"] == [{"functionCall": {"name": "lookup", "args": {"q": "x"}}}]
    assert contents[1]["parts"] == [{"functionResponse": {"name": "lookup", "response": {"result": "answer"}}}]


@pytest.mark.asyncio
async def test_openai_deferred_failure_is_reported(monkeypatch) -> None:
    async def fail(*_args, **_kwargs):
        raise RuntimeError("provider failed")

    monkeypatch.setattr(openai_completions, "stream_openai_chat_completions", fail)
    result = openai_completions.stream(MODEL, {"messages": []}, {"apiKey": "x"})
    message = await result.result()
    assert message["stopReason"] == "error"
    assert "provider failed" in message["errorMessage"]


def test_openai_stream_starts_without_running_loop(monkeypatch) -> None:
    async def complete(*_args, **_kwargs):
        stream = create_assistant_message_event_stream()
        message = {"role": "assistant", "content": [], "api": "openai-completions", "provider": "p", "model": "m", "usage": {}, "stopReason": "stop", "timestamp": 0}
        stream.end(message)
        return stream

    monkeypatch.setattr(openai_completions, "stream_openai_chat_completions", complete)
    result = openai_completions.stream(MODEL, {"messages": []}, {"apiKey": "x"})
    message = asyncio.run(result.result())
    assert message["stopReason"] == "stop"


class _Response:
    def __init__(self, lines, status_code=200):
        self.lines = lines
        self.status_code = status_code
        self.headers = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def aread(self):
        return b""

    async def _lines(self):
        for line in self.lines:
            yield line

    def aiter_lines(self):
        return self._lines()


class _Client:
    response = None

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    def stream(self, *_args, **_kwargs):
        return self.response


@pytest.mark.asyncio
async def test_http_malformed_frame_is_terminal_parse_error(monkeypatch) -> None:
    _Client.response = _Response(["data: not-json"])
    monkeypatch.setattr("earendil_works.pi_ai.api._http_stream.httpx.AsyncClient", _Client)
    result = await stream_openai_chat_completions(MODEL, {"messages": []}, {"apiKey": "x"}, payload={})
    message = await result.result()
    assert message["stopReason"] == "error"
    assert message["error"]["type"] == "parse"


@pytest.mark.asyncio
async def test_http_cancellation_interrupts_stalled_line(monkeypatch) -> None:
    signal = threading.Event()

    async def stalled():
        while not signal.is_set():
            await asyncio.sleep(0.01)
        await asyncio.Future()
        yield "never"

    response = _Response([])
    response.aiter_lines = stalled
    _Client.response = response
    monkeypatch.setattr("earendil_works.pi_ai.api._http_stream.httpx.AsyncClient", _Client)
    result = await stream_openai_chat_completions(MODEL, {"messages": []}, {"apiKey": "x", "signal": signal}, payload={})
    asyncio.get_running_loop().call_later(0.03, signal.set)
    message = await asyncio.wait_for(result.result(), 1)
    assert message["stopReason"] == "aborted"


@pytest.mark.asyncio
async def test_http_tool_partial_updates_partial_message(monkeypatch) -> None:
    chunks = [
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c","function":{"name":"lookup","arguments":"{\\"q\\":"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":" \\"x\\"}"}}]}}]}',
        "data: [DONE]",
    ]
    _Client.response = _Response(chunks)
    monkeypatch.setattr("earendil_works.pi_ai.api._http_stream.httpx.AsyncClient", _Client)
    result = await stream_openai_chat_completions(MODEL, {"messages": []}, {"apiKey": "x"}, payload={})
    events = [event async for event in result]
    deltas = [event for event in events if event["type"] == "toolcall_delta"]
    assert deltas[0]["partial"]["content"][0]["name"] == "lookup"
    assert deltas[-1]["partial"]["content"][0]["arguments"] == {"q": "x"}


@pytest.mark.asyncio
async def test_lazy_forward_reports_source_result_failure() -> None:
    class Source:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def result(self):
            raise RuntimeError("inner failed")

    model = {"id": "m", "api": "x", "provider": "p"}
    result = lazy_stream(model, lambda: _resolved(Source()))
    message = await result.result()
    assert message["stopReason"] == "error"
    assert "inner failed" in message["errorMessage"]


async def _resolved(source):
    return source


@pytest.mark.parametrize("module", [azure_openai_responses_lazy, bedrock_converse_stream_lazy, openai_codex_responses_lazy, openai_responses_lazy])
def test_lazy_provider_modules_delegate_to_lazy_api(monkeypatch, module) -> None:
    called = []
    monkeypatch.setattr(module, "lazy_api", lambda load: called.append(load) or {"stream": object()})
    module_fn = next(value for name, value in vars(module).items() if name.endswith("_api") and callable(value) and name != "lazy_api")
    assert module_fn()["stream"] is not None
    assert len(called) == 1


def test_provider_transforms_preserve_image_and_thinking_signature() -> None:
    context = {
        "messages": [
            {"role": "user", "content": [{"type": "image", "mimeType": "image/png", "data": "abc"}]},
            {"role": "assistant", "content": [{"type": "thinking", "thinking": "step", "thinkingSignature": "sig"}]},
        ]
    }
    openai = context_to_openai_messages(context)
    _, anthropic = context_to_anthropic_messages(context)
    assert openai[0]["content"][0]["type"] == "image_url"
    assert anthropic[0]["content"][0] == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "abc"}}
    assert anthropic[1]["content"][0]["signature"] == "sig"


def test_parse_error_classification() -> None:
    error = error_message(MODEL, json.JSONDecodeError("bad", "x", 0))
    assert error["error"]["type"] == "parse"
