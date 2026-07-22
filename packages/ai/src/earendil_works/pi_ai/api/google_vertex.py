"""google-vertex API module."""
from __future__ import annotations
from typing import Any
from ..types import Context, Model, SimpleStreamOptions, StreamOptions
from ..utils.event_stream import AssistantMessageEventStream
from .google_generative_ai import stream as _gstream

def stream(model: Model, context: Context, options: StreamOptions | None = None) -> AssistantMessageEventStream:
    return _gstream(model, context, options)

def stream_simple(model: Model, context: Context, options: SimpleStreamOptions | None = None) -> AssistantMessageEventStream:
    return stream(model, context, options)  # type: ignore[arg-type]

def google_vertex_api() -> dict[str, Any]:
    return {"stream": stream, "streamSimple": stream_simple, "stream_simple": stream_simple}

googleVertexApi = google_vertex_api
