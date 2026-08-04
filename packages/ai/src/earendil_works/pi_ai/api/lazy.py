"""lazyStream / lazyApi — port of api/lazy.ts."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterable, Awaitable, Callable
from typing import Any

from ..types import AssistantMessage, AssistantMessageEvent, Model, empty_usage
from ..utils.event_stream import AssistantMessageEventStream


def create_setup_error_message(model: Model, error: Any) -> AssistantMessage:
    return {
        "role": "assistant",
        "content": [],
        "api": model["api"],
        "provider": model["provider"],
        "model": model["id"],
        "usage": empty_usage(),
        "stopReason": "error",
        "errorMessage": str(error),
        "timestamp": int(time.time() * 1000),
    }


async def forward_stream(
    target: AssistantMessageEventStream,
    source: AsyncIterable[AssistantMessageEvent],
) -> None:
    async for event in source:
        target.push(event)
    if hasattr(source, "result"):
        result = await source.result()  # type: ignore[misc]
        target.end(result)
        return
    target.end()


def lazy_stream(
    model: Model,
    setup: Callable[[], Awaitable[AsyncIterable[AssistantMessageEvent]]],
) -> AssistantMessageEventStream:
    outer = AssistantMessageEventStream()

    async def run() -> None:
        try:
            inner = await setup()
            await forward_stream(outer, inner)
        except Exception as error:
            message = create_setup_error_message(model, error)
            outer.push({"type": "error", "reason": "error", "error": message})
            outer.end(message)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(run())
    except RuntimeError:
        outer._pending_setup = run  # type: ignore[attr-defined]

        original = outer._iterate

        async def _iterate_with_setup():
            if getattr(outer, "_setup_started", False) is False:
                outer._setup_started = True  # type: ignore[attr-defined]
                asyncio.create_task(run())
            async for item in original():
                yield item

        outer._iterate = _iterate_with_setup  # type: ignore[method-assign]

    return outer


def lazy_api(load: Callable[[], Awaitable[Any]]) -> dict[str, Any]:
    def stream(model, context, options=None):
        async def setup():
            streams = await load()
            return streams.stream(model, context, options) if hasattr(streams, "stream") else streams["stream"](model, context, options)

        return lazy_stream(model, setup)

    def stream_simple(model, context, options=None):
        async def setup():
            streams = await load()
            if hasattr(streams, "stream_simple"):
                return streams.stream_simple(model, context, options)
            if hasattr(streams, "streamSimple"):
                return streams.streamSimple(model, context, options)
            if isinstance(streams, dict):
                fn = streams.get("streamSimple") or streams.get("stream_simple") or streams["stream"]
                return fn(model, context, options)
            return streams.stream(model, context, options)

        return lazy_stream(model, setup)

    return {"stream": stream, "streamSimple": stream_simple, "stream_simple": stream_simple}
