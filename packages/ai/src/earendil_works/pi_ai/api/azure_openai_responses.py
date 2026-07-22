"""azure-openai-responses API module."""
from __future__ import annotations
from typing import Any
from ..types import Context, Model, SimpleStreamOptions, StreamOptions
from ..utils.event_stream import AssistantMessageEventStream
from .openai_responses import stream as _rstream

def stream(model: Model, context: Context, options: StreamOptions | None = None) -> AssistantMessageEventStream:
    return _rstream(model, context, options)

def stream_simple(model: Model, context: Context, options: SimpleStreamOptions | None = None) -> AssistantMessageEventStream:
    return stream(model, context, options)  # type: ignore[arg-type]

def azure_openai_responses_api() -> dict[str, Any]:
    return {"stream": stream, "streamSimple": stream_simple, "stream_simple": stream_simple}

azureOpenAIResponsesApi = azure_openai_responses_api
