"""Faux provider — port of providers/faux.ts for offline tests."""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ..models import Provider, create_provider
from ..types import (
    AssistantMessage,
    Context,
    Model,
    SimpleStreamOptions,
    StreamOptions,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    Usage,
    empty_usage,
    Message,
)
from ..utils.event_stream import AssistantMessageEventStream, create_assistant_message_event_stream
from ..utils.text import extract_text

DEFAULT_API = "faux"
DEFAULT_PROVIDER = "faux"
DEFAULT_MODEL_ID = "faux-1"
DEFAULT_MODEL_NAME = "Faux Model"
DEFAULT_BASE_URL = "http://localhost:0"
DEFAULT_MIN_TOKEN_SIZE = 3
DEFAULT_MAX_TOKEN_SIZE = 5

FauxContentBlock = TextContent | ThinkingContent | ToolCall
FauxResponseFactory = Callable[
    [Context, StreamOptions | None, dict[str, int], Model],
    AssistantMessage | Awaitable[AssistantMessage],
]
FauxResponseStep = AssistantMessage | FauxResponseFactory


def faux_text(text: str) -> TextContent:
    return {"type": "text", "text": text}


def faux_thinking(thinking: str) -> ThinkingContent:
    return {"type": "thinking", "thinking": thinking}


def faux_tool_call(
    name: str,
    arguments: dict[str, Any],
    *,
    id: str | None = None,
) -> ToolCall:
    return {
        "type": "toolCall",
        "id": id or f"call_{int(time.time()*1000)}_{random.randint(0,9999)}",
        "name": name,
        "arguments": arguments,
    }


def _normalize_content(
    content: str | FauxContentBlock | list[FauxContentBlock],
) -> list[FauxContentBlock]:
    if isinstance(content, str):
        return [faux_text(content)]
    if isinstance(content, dict):
        return [content]  # type: ignore[list-item]
    return list(content)


def faux_assistant_message(
    content: str | FauxContentBlock | list[FauxContentBlock],
    *,
    stop_reason: str = "stop",
    error_message: str | None = None,
    api: str = DEFAULT_API,
    provider: str = DEFAULT_PROVIDER,
    model: str = DEFAULT_MODEL_ID,
) -> AssistantMessage:
    blocks = _normalize_content(content)
    # toolUse if any tool calls and stop is default
    if any(b.get("type") == "toolCall" for b in blocks) and stop_reason == "stop":
        stop_reason = "toolUse"
    msg: AssistantMessage = {
        "role": "assistant",
        "content": blocks,  # type: ignore[typeddict-item]
        "api": api,
        "provider": provider,
        "model": model,
        "usage": empty_usage(),
        "stopReason": stop_reason,  # type: ignore[typeddict-item]
        "timestamp": int(time.time() * 1000),
    }
    if error_message:
        msg["errorMessage"] = error_message
    return msg


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _random_id(prefix: str) -> str:
    return f"{prefix}:{int(time.time()*1000)}:{random.randrange(1<<20):x}"


def _content_to_text(content: Any) -> str:
    return extract_text(content)


def _assistant_content_to_text(content: list[Any]) -> str:
    parts = []
    for block in content:
        if block.get("type") == "text":
            parts.append(block.get("text") or "")
        elif block.get("type") == "thinking":
            parts.append(block.get("thinking") or "")
        elif block.get("type") == "toolCall":
            parts.append(json.dumps(block.get("arguments") or {}))
    return "\n".join(parts)


def _message_to_text(message: Message) -> str:
    role = message.get("role")
    if role == "user":
        return _content_to_text(message.get("content"))
    if role == "assistant":
        return _assistant_content_to_text(message.get("content") or [])  # type: ignore[arg-type]
    if role == "toolResult":
        tr: ToolResultMessage = message  # type: ignore[assignment]
        return "\n".join([tr.get("toolName") or "", _content_to_text(tr.get("content"))])
    return ""


def _serialize_context(context: Context) -> str:
    parts = []
    if context.get("systemPrompt"):
        parts.append(context["systemPrompt"])
    for m in context.get("messages") or []:
        parts.append(_message_to_text(m))
    return "\n".join(parts)


def _common_prefix_length(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def _with_usage_estimate(
    message: AssistantMessage,
    context: Context,
    options: StreamOptions | None,
    prompt_cache: dict[str, str],
) -> AssistantMessage:
    serialized = _serialize_context(context)
    cache_key = message.get("provider") or "faux"
    prev = prompt_cache.get(cache_key, "")
    prefix = _common_prefix_length(prev, serialized)
    prompt_cache[cache_key] = serialized
    input_tokens = _estimate_tokens(serialized)
    cache_read = _estimate_tokens(serialized[:prefix]) if prefix else 0
    output_tokens = _estimate_tokens(_assistant_content_to_text(message.get("content") or []))
    usage: Usage = empty_usage()
    usage["cacheRead"] = cache_read
    usage["cacheWrite"] = max(0, input_tokens - cache_read)
    usage["input"] = max(0, input_tokens - usage["cacheRead"] - usage["cacheWrite"])
    usage["output"] = output_tokens
    usage["totalTokens"] = usage["input"] + output_tokens + usage["cacheRead"] + usage["cacheWrite"]
    message = {**message, "usage": usage}  # type: ignore[assignment]
    return message


def _split_string_by_token_size(text: str, min_token_size: int, max_token_size: int) -> list[str]:
    if not text:
        return []
    chunks: list[str] = []
    i = 0
    while i < len(text):
        size = random.randint(min_token_size, max_token_size)
        chunks.append(text[i : i + size])
        i += size
    return chunks


def _clone_message(message: AssistantMessage, api: str, provider: str, model_id: str) -> AssistantMessage:
    cloned = json.loads(json.dumps(message))
    cloned["api"] = api
    cloned["provider"] = provider
    cloned["model"] = model_id
    return cloned  # type: ignore[return-value]


def _create_error_message(error: Any, api: str, provider: str, model_id: str) -> AssistantMessage:
    return {
        "role": "assistant",
        "content": [],
        "api": api,
        "provider": provider,
        "model": model_id,
        "usage": empty_usage(),
        "stopReason": "error",
        "errorMessage": str(error),
        "timestamp": int(time.time() * 1000),
    }


def _create_aborted_message(partial: AssistantMessage) -> AssistantMessage:
    msg = json.loads(json.dumps(partial))
    msg["stopReason"] = "aborted"
    msg["errorMessage"] = "aborted"
    return msg  # type: ignore[return-value]


async def _schedule_chunk(chunk: str, tokens_per_second: float | None) -> None:
    if tokens_per_second and tokens_per_second > 0:
        await asyncio.sleep(max(0.0, len(chunk) / max(tokens_per_second * 4, 1e-6)))


def _is_aborted(signal: Any) -> bool:
    if signal is None:
        return False
    if hasattr(signal, "is_set"):
        return bool(signal.is_set())
    if hasattr(signal, "aborted"):
        return bool(signal.aborted)
    return False


async def _stream_with_deltas(
    stream: AssistantMessageEventStream,
    message: AssistantMessage,
    min_token_size: int,
    max_token_size: int,
    tokens_per_second: float | None,
    signal: Any,
) -> None:
    partial: AssistantMessage = {**message, "content": []}
    if _is_aborted(signal):
        aborted = _create_aborted_message(partial)
        stream.push({"type": "error", "reason": "aborted", "error": aborted})
        stream.end(aborted)
        return

    stream.push({"type": "start", "partial": json.loads(json.dumps(partial))})

    for index, block in enumerate(message.get("content") or []):
        if _is_aborted(signal):
            aborted = _create_aborted_message(partial)
            stream.push({"type": "error", "reason": "aborted", "error": aborted})
            stream.end(aborted)
            return

        if block.get("type") == "thinking":
            partial["content"] = [*partial["content"], {"type": "thinking", "thinking": ""}]
            stream.push(
                {
                    "type": "thinking_start",
                    "contentIndex": index,
                    "partial": json.loads(json.dumps(partial)),
                }
            )
            for chunk in _split_string_by_token_size(
                block.get("thinking") or "", min_token_size, max_token_size
            ):
                await _schedule_chunk(chunk, tokens_per_second)
                if _is_aborted(signal):
                    aborted = _create_aborted_message(partial)
                    stream.push({"type": "error", "reason": "aborted", "error": aborted})
                    stream.end(aborted)
                    return
                partial["content"][index]["thinking"] += chunk  # type: ignore[index]
                stream.push(
                    {
                        "type": "thinking_delta",
                        "contentIndex": index,
                        "delta": chunk,
                        "partial": json.loads(json.dumps(partial)),
                    }
                )
            stream.push(
                {
                    "type": "thinking_end",
                    "contentIndex": index,
                    "content": block.get("thinking") or "",
                    "partial": json.loads(json.dumps(partial)),
                }
            )
            continue

        if block.get("type") == "text":
            partial["content"] = [*partial["content"], {"type": "text", "text": ""}]
            stream.push(
                {
                    "type": "text_start",
                    "contentIndex": index,
                    "partial": json.loads(json.dumps(partial)),
                }
            )
            for chunk in _split_string_by_token_size(block.get("text") or "", min_token_size, max_token_size):
                await _schedule_chunk(chunk, tokens_per_second)
                if _is_aborted(signal):
                    aborted = _create_aborted_message(partial)
                    stream.push({"type": "error", "reason": "aborted", "error": aborted})
                    stream.end(aborted)
                    return
                partial["content"][index]["text"] += chunk  # type: ignore[index]
                stream.push(
                    {
                        "type": "text_delta",
                        "contentIndex": index,
                        "delta": chunk,
                        "partial": json.loads(json.dumps(partial)),
                    }
                )
            stream.push(
                {
                    "type": "text_end",
                    "contentIndex": index,
                    "content": block.get("text") or "",
                    "partial": json.loads(json.dumps(partial)),
                }
            )
            continue

        # toolCall
        partial["content"] = [
            *partial["content"],
            {
                "type": "toolCall",
                "id": block.get("id") or f"call_{index}",
                "name": block.get("name") or "",
                "arguments": {},
            },
        ]
        stream.push(
            {
                "type": "toolcall_start",
                "contentIndex": index,
                "partial": json.loads(json.dumps(partial)),
            }
        )
        args_text = json.dumps(block.get("arguments") or {})
        for chunk in _split_string_by_token_size(args_text, min_token_size, max_token_size):
            await _schedule_chunk(chunk, tokens_per_second)
            if _is_aborted(signal):
                aborted = _create_aborted_message(partial)
                stream.push({"type": "error", "reason": "aborted", "error": aborted})
                stream.end(aborted)
                return
            stream.push(
                {
                    "type": "toolcall_delta",
                    "contentIndex": index,
                    "delta": chunk,
                    "partial": json.loads(json.dumps(partial)),
                }
            )
        partial["content"][index]["arguments"] = block.get("arguments") or {}  # type: ignore[index]
        stream.push(
            {
                "type": "toolcall_end",
                "contentIndex": index,
                "toolCall": block,  # type: ignore[typeddict-item]
                "partial": json.loads(json.dumps(partial)),
            }
        )

    if message.get("stopReason") in ("error", "aborted"):
        stream.push(
            {
                "type": "error",
                "reason": message["stopReason"],  # type: ignore[typeddict-item]
                "error": message,
            }
        )
        stream.end(message)
        return

    reason = message.get("stopReason") or "stop"
    if reason not in ("stop", "length", "toolUse"):
        reason = "stop"
    stream.push({"type": "done", "reason": reason, "message": message})  # type: ignore[arg-type]
    stream.end(message)


def create_faux_core(options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    api = options.get("api") or _random_id(DEFAULT_API)
    provider = options.get("provider") or DEFAULT_PROVIDER
    min_token_size = max(
        1,
        min(
            (options.get("tokenSize") or {}).get("min", DEFAULT_MIN_TOKEN_SIZE),
            (options.get("tokenSize") or {}).get("max", DEFAULT_MAX_TOKEN_SIZE),
        ),
    )
    max_token_size = max(min_token_size, (options.get("tokenSize") or {}).get("max", DEFAULT_MAX_TOKEN_SIZE))
    pending: list[FauxResponseStep] = []
    tokens_per_second = options.get("tokensPerSecond")
    state = {"callCount": 0}
    prompt_cache: dict[str, str] = {}

    model_defs = options.get("models") or [
        {
            "id": DEFAULT_MODEL_ID,
            "name": DEFAULT_MODEL_NAME,
            "reasoning": False,
            "input": ["text", "image"],
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            "contextWindow": 128000,
            "maxTokens": 16384,
        }
    ]
    models: list[Model] = [
        {
            "id": d["id"],
            "name": d.get("name") or d["id"],
            "api": api,
            "provider": provider,
            "baseUrl": DEFAULT_BASE_URL,
            "reasoning": bool(d.get("reasoning", False)),
            "input": d.get("input") or ["text", "image"],  # type: ignore[typeddict-item]
            "cost": d.get("cost") or {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            "contextWindow": int(d.get("contextWindow") or 128000),
            "maxTokens": int(d.get("maxTokens") or 16384),
        }
        for d in model_defs
    ]

    def stream(
        request_model: Model,
        context: Context,
        stream_options: StreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        outer = create_assistant_message_event_stream()
        step = pending.pop(0) if pending else None
        state["callCount"] += 1

        async def run() -> None:
            try:
                on_response = (stream_options or {}).get("onResponse")
                if on_response:
                    res = on_response({"status": 200, "headers": {}}, request_model)
                    if hasattr(res, "__await__"):
                        await res
                if step is None:
                    message = _create_error_message(
                        Exception("No more faux responses queued"),
                        api,
                        provider,
                        request_model["id"],
                    )
                    message = _with_usage_estimate(message, context, stream_options, prompt_cache)
                    outer.push({"type": "error", "reason": "error", "error": message})
                    outer.end(message)
                    return
                if callable(step):
                    resolved = step(context, stream_options, state, request_model)
                    if hasattr(resolved, "__await__"):
                        resolved = await resolved  # type: ignore[misc]
                else:
                    resolved = step
                message = _clone_message(resolved, api, provider, request_model["id"])  # type: ignore[arg-type]
                message = _with_usage_estimate(message, context, stream_options, prompt_cache)
                await _stream_with_deltas(
                    outer,
                    message,
                    min_token_size,
                    max_token_size,
                    tokens_per_second,
                    (stream_options or {}).get("signal"),
                )
            except Exception as error:
                message = _create_error_message(error, api, provider, request_model["id"])
                outer.push({"type": "error", "reason": "error", "error": message})
                outer.end(message)

        try:
            asyncio.get_running_loop().create_task(run())
        except RuntimeError:
            outer.start(run)
        return outer

    def stream_simple(
        stream_model: Model,
        context: Context,
        stream_options: SimpleStreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        return stream(stream_model, context, stream_options)  # type: ignore[arg-type]

    def get_model(requested_model_id: str | None = None) -> Model | None:
        if not requested_model_id:
            return models[0]
        return next((m for m in models if m["id"] == requested_model_id), None)

    def set_responses(responses: list[FauxResponseStep]) -> None:
        pending.clear()
        pending.extend(list(responses))

    def append_responses(responses: list[FauxResponseStep]) -> None:
        pending.extend(list(responses))

    return {
        "api": api,
        "provider": provider,
        "models": models,
        "stream": stream,
        "streamSimple": stream_simple,
        "stream_simple": stream_simple,
        "getModel": get_model,
        "state": state,
        "setResponses": set_responses,
        "appendResponses": append_responses,
        "getPendingResponseCount": lambda: len(pending),
        "_pending": pending,
    }


def faux_provider(options: dict[str, Any] | None = None) -> dict[str, Any]:
    core = create_faux_core(options)

    async def resolve(_args: dict[str, Any]) -> dict[str, Any]:
        return {"auth": {}, "source": "faux"}

    provider = create_provider(
        {
            "id": core["provider"],
            "auth": {"apiKey": {"name": "Faux", "resolve": resolve}},
            "models": core["models"],
            "api": {
                "stream": core["stream"],
                "streamSimple": core["streamSimple"],
                "stream_simple": core["stream_simple"],
            },
        }
    )
    return {
        "provider": provider,
        "api": core["api"],
        "models": core["models"],
        "getModel": core["getModel"],
        "state": core["state"],
        "setResponses": core["setResponses"],
        "appendResponses": core["appendResponses"],
        "getPendingResponseCount": core["getPendingResponseCount"],
    }


# camelCase aliases
fauxProvider = faux_provider
fauxAssistantMessage = faux_assistant_message
fauxText = faux_text
fauxThinking = faux_thinking
fauxToolCall = faux_tool_call
createFauxCore = create_faux_core
