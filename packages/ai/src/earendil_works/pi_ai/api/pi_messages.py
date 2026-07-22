"""pi-messages API module (Radius gateway)."""
from __future__ import annotations
from typing import Any
from ..types import Context, Model, SimpleStreamOptions, StreamOptions
from ..utils.event_stream import AssistantMessageEventStream
from .openai_completions import stream as _compat_stream

def stream(model: Model, context: Context, options: StreamOptions | None = None) -> AssistantMessageEventStream:
    return _compat_stream(model, context, options)

def stream_simple(model: Model, context: Context, options: SimpleStreamOptions | None = None) -> AssistantMessageEventStream:
    return stream(model, context, options)  # type: ignore[arg-type]

def pi_messages_api() -> dict[str, Any]:
    return {"stream": stream, "streamSimple": stream_simple, "stream_simple": stream_simple}

piMessagesApi = pi_messages_api
