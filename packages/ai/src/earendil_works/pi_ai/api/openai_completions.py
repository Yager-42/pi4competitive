"""openai-completions API — port of api/openai-completions.ts (stream surface)."""

from __future__ import annotations

from typing import Any

from ..types import Context, Model, SimpleStreamOptions, StreamOptions
from ..utils.event_stream import AssistantMessageEventStream
from .transform_messages import build_openai_completions_payload
from ._http_stream import stream_openai_chat_completions


def stream(
    model: Model,
    context: Context,
    options: StreamOptions | None = None,
) -> AssistantMessageEventStream:
    payload = build_openai_completions_payload(model, context, options)  # type: ignore[arg-type]
    return _deferred(model, context, options, payload)


def stream_simple(
    model: Model,
    context: Context,
    options: SimpleStreamOptions | None = None,
) -> AssistantMessageEventStream:
    return stream(model, context, options)  # type: ignore[arg-type]


def open_ai_completions_api() -> dict[str, Any]:
    return {"stream": stream, "streamSimple": stream_simple, "stream_simple": stream_simple}


# alias for TS naming
openAICompletionsApi = open_ai_completions_api


def _deferred(model, context, options, payload):
    import asyncio
    from ..utils.event_stream import create_assistant_message_event_stream

    outer = create_assistant_message_event_stream()

    async def run():
        inner = await stream_openai_chat_completions(model, context, options, payload=payload)
        async for event in inner:
            outer.push(event)
        try:
            outer.end(await inner.result())
        except Exception:
            outer.end()

    try:
        asyncio.get_running_loop().create_task(run())
    except RuntimeError:
        pass
    return outer
