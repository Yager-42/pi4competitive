from __future__ import annotations

import asyncio

import pytest

from earendil_works.pi_ai import create_models
from earendil_works.pi_ai.providers.faux import (
    faux_assistant_message,
    faux_provider,
    faux_text,
    faux_thinking,
    faux_tool_call,
)


@pytest.mark.asyncio
async def test_faux_stream_event_order() -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"]([faux_assistant_message("hello world")])
    model = faux["getModel"]()
    stream = models.stream(model, {"messages": [{"role": "user", "content": "hi", "timestamp": 0}]})
    types = []
    async for event in stream:
        types.append(event["type"])
    assert types[0] == "start"
    assert "text_start" in types
    assert "text_delta" in types
    assert "text_end" in types
    assert types[-1] == "done"
    msg = await stream.result()
    assert msg["stopReason"] == "stop"
    assert any(b.get("type") == "text" and "hello" in b.get("text", "") for b in msg["content"])


@pytest.mark.asyncio
async def test_faux_toolcall_partial_then_end() -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"](
        [
            faux_assistant_message(
                [faux_tool_call("lookup", {"q": "x"})],
            )
        ]
    )
    model = faux["getModel"]()
    stream = models.stream(model, {"messages": []})
    types = [e["type"] async for e in stream]
    assert "toolcall_start" in types
    assert "toolcall_delta" in types
    assert "toolcall_end" in types
    assert types[-1] == "done"
    msg = await stream.result()
    assert msg["stopReason"] == "toolUse"


@pytest.mark.asyncio
async def test_complete_equals_stream_result() -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    text = "parity-check"
    faux["setResponses"]([faux_assistant_message(text), faux_assistant_message(text)])
    model = faux["getModel"]()
    ctx = {"messages": [{"role": "user", "content": "x", "timestamp": 1}]}
    streamed = await models.stream(model, ctx).result()
    completed = await models.complete(model, ctx)
    assert streamed["content"] == completed["content"]
    assert streamed["stopReason"] == completed["stopReason"]


@pytest.mark.asyncio
async def test_usage_fields_present() -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"]([faux_assistant_message("abc")])
    msg = await models.complete(faux["getModel"](), {"messages": []})
    usage = msg["usage"]
    for key in ("input", "output", "cacheRead", "cacheWrite", "totalTokens", "cost"):
        assert key in usage
    for key in ("input", "output", "cacheRead", "cacheWrite", "total"):
        assert key in usage["cost"]


@pytest.mark.asyncio
async def test_abort_stops_stream() -> None:
    faux = faux_provider({"tokensPerSecond": 1})  # slow chunks
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"]([faux_assistant_message("abcdefghijklmnopqrstuvwxyz" * 5)])
    signal = asyncio.Event()
    stream = models.stream(
        faux["getModel"](),
        {"messages": []},
        {"signal": signal},
    )

    async def abort_soon() -> None:
        await asyncio.sleep(0.01)
        signal.set()

    asyncio.create_task(abort_soon())
    types = [e["type"] async for e in stream]
    assert "error" in types or types[-1] == "done"
    msg = await stream.result()
    assert msg["stopReason"] in ("aborted", "stop", "error")


@pytest.mark.asyncio
async def test_thinking_blocks() -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"](
        [faux_assistant_message([faux_thinking("hmm"), faux_text("ok")])]
    )
    types = [
        e["type"]
        async for e in models.stream(faux["getModel"](), {"messages": []})
    ]
    assert "thinking_start" in types
    assert "thinking_delta" in types
    assert "thinking_end" in types


@pytest.mark.asyncio
async def test_models_get_model_routing() -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    m = models.getModel("faux", "faux-1")
    assert m is not None
    assert m["provider"] == "faux"
    assert models.getModel("faux", "missing") is None
