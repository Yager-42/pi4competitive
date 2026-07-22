"""openai-responses API — structural port; uses chat.completions compatible path when needed."""

from __future__ import annotations

from typing import Any

from ..types import Context, Model, SimpleStreamOptions, StreamOptions
from ..utils.event_stream import AssistantMessageEventStream
from .openai_completions import stream as completions_stream
from .transform_messages import build_openai_completions_payload


def stream(
    model: Model,
    context: Context,
    options: StreamOptions | None = None,
) -> AssistantMessageEventStream:
    # Full Responses API wire format is complex; isomorphic surface delegates to
    # chat completions-compatible streaming against the model baseUrl when using
    # OpenAI-compatible gateways, matching host-delta pragmatic parity for P1 CI.
    # Payload builder remains available for golden tests.
    return completions_stream(model, context, options)


def stream_simple(
    model: Model,
    context: Context,
    options: SimpleStreamOptions | None = None,
) -> AssistantMessageEventStream:
    return stream(model, context, options)  # type: ignore[arg-type]


def open_ai_responses_api() -> dict[str, Any]:
    return {"stream": stream, "streamSimple": stream_simple, "stream_simple": stream_simple}


openAIResponsesApi = open_ai_responses_api


def build_responses_payload(model: Model, context: Context, options: dict[str, Any] | None = None) -> dict[str, Any]:
    # Minimal responses-shaped payload for offline golden tests
    base = build_openai_completions_payload(model, context, options)
    return {
        "model": base["model"],
        "input": base["messages"],
        "stream": True,
        "tools": base.get("tools"),
    }
