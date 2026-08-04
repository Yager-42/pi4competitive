"""Shared HTTP/SSE streaming utilities for provider APIs."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal

import httpx

from ..types import (
    AssistantMessage,
    AssistantMessageEvent,
    Context,
    ErrorInfo,
    Model,
    StreamOptions,
    ToolCall,
    empty_usage,
)
from ..utils.event_stream import AssistantMessageEventStream, create_assistant_message_event_stream
from ..utils.json_parse import parse_partial_json

ErrorType = Literal["timeout", "connection", "http_error", "parse", "aborted", "other"]


def error_message(
    model: Model,
    error: Any,
    *,
    aborted: bool = False,
    status_code: int | None = None,
) -> AssistantMessage:
    """Build an error AssistantMessage (ADR 0015: structured ``error`` field).

    Classification: HTTP ``status_code`` -> ``http_error``; httpx transport
    exceptions -> ``timeout`` / ``connection`` / ``other``; abort -> ``aborted``.
    ``errorMessage`` text is kept for backward compatibility.
    """
    if aborted:
        error_type: ErrorType = "aborted"
    elif status_code is not None:
        error_type = "http_error"
    elif isinstance(error, json.JSONDecodeError):
        error_type = "parse"
    elif isinstance(error, httpx.TimeoutException):
        error_type = "timeout"
    elif isinstance(error, (httpx.ConnectError, ConnectionError)):
        error_type = "connection"
    elif isinstance(error, httpx.ReadError):
        error_type = "other"
    else:
        error_type = "other"
    msg: AssistantMessage = {
        "role": "assistant",
        "content": [],
        "api": model["api"],
        "provider": model["provider"],
        "model": model["id"],
        "usage": empty_usage(),
        "stopReason": "aborted" if aborted else "error",
        "errorMessage": str(error),
        "timestamp": int(time.time() * 1000),
    }
    info: ErrorInfo = {"type": error_type, "message": str(error)}
    if status_code is not None:
        info["statusCode"] = status_code
    msg["error"] = info
    return msg


def is_aborted(options: StreamOptions | None) -> bool:
    if not options:
        return False
    signal = options.get("signal")
    if signal is None:
        return False
    if hasattr(signal, "is_set"):
        return bool(signal.is_set())
    if hasattr(signal, "aborted"):
        return bool(signal.aborted)
    return False


async def run_setup_stream(
    model: Model,
    runner: Callable[[AssistantMessageEventStream], Any],
) -> AssistantMessageEventStream:
    stream = create_assistant_message_event_stream()

    async def task() -> None:
        try:
            await runner(stream)
        except Exception as exc:
            msg = error_message(model, exc)
            stream.push({"type": "error", "reason": "error", "error": msg})
            stream.end(msg)

    import asyncio

    asyncio.create_task(task())
    return stream


async def stream_openai_chat_completions(
    model: Model,
    context: Context,
    options: StreamOptions | None,
    *,
    payload: dict[str, Any],
    url: str | None = None,
) -> AssistantMessageEventStream:
    """Stream OpenAI-compatible chat.completions SSE."""

    async def runner(stream: AssistantMessageEventStream) -> None:
        if is_aborted(options):
            msg = error_message(model, "aborted", aborted=True)
            stream.push({"type": "error", "reason": "aborted", "error": msg})
            stream.end(msg)
            return

        api_key = (options or {}).get("apiKey")
        if not api_key:
            msg = error_message(model, "Missing API key")
            stream.push({"type": "error", "reason": "error", "error": msg})
            stream.end(msg)
            return

        base = model.get("baseUrl") or "https://api.openai.com/v1"
        endpoint = url or f"{base.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        extra = (options or {}).get("headers") or {}
        for k, v in extra.items():
            if v is not None:
                headers[k] = v

        body = payload
        on_payload = (options or {}).get("onPayload")
        if on_payload:
            replaced = await _maybe_await(on_payload(body, model))
            if replaced is not None:
                body = replaced

        partial: AssistantMessage = {
            "role": "assistant",
            "content": [],
            "api": model["api"],
            "provider": model["provider"],
            "model": model["id"],
            "usage": empty_usage(),
            "stopReason": "stop",
            "timestamp": int(time.time() * 1000),
        }
        stream.push({"type": "start", "partial": dict(partial)})

        text_index: int | None = None
        tool_buffers: dict[int, dict[str, Any]] = {}
        finish_reason = "stop"

        timeout = ((options or {}).get("timeoutMs") or 600_000) / 1000.0
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", endpoint, headers=headers, json=body) as resp:
                on_response = (options or {}).get("onResponse")
                if on_response:
                    await _maybe_await(
                        on_response(
                            {"status": resp.status_code, "headers": dict(resp.headers)},
                            model,
                        )
                    )
                if resp.status_code >= 400:
                    text = (await resp.aread()).decode("utf-8", errors="replace")
                    msg = error_message(model, f"HTTP {resp.status_code}: {text[:500]}", status_code=resp.status_code)
                    stream.push({"type": "error", "reason": "error", "error": msg})
                    stream.end(msg)
                    return

                line_iter = resp.aiter_lines().__aiter__()
                while True:
                    next_line = asyncio.create_task(line_iter.__anext__())
                    try:
                        while not next_line.done():
                            await asyncio.wait({next_line}, timeout=0.1)
                            if is_aborted(options):
                                next_line.cancel()
                                await asyncio.gather(next_line, return_exceptions=True)
                                msg = error_message(model, "aborted", aborted=True)
                                stream.push({"type": "error", "reason": "aborted", "error": msg})
                                stream.end(msg)
                                return
                        try:
                            line = next_line.result()
                        except StopAsyncIteration:
                            break
                    finally:
                        if not next_line.done():
                            next_line.cancel()
                            await asyncio.gather(next_line, return_exceptions=True)
                    if is_aborted(options):
                        msg = error_message(model, "aborted", aborted=True)
                        stream.push({"type": "error", "reason": "aborted", "error": msg})
                        stream.end(msg)
                        return
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError as exc:
                        msg = error_message(model, exc)
                        stream.push({"type": "error", "reason": "error", "error": msg})
                        stream.end(msg)
                        return
                    if not isinstance(chunk, dict):
                        msg = error_message(model, "Invalid SSE data frame")
                        stream.push({"type": "error", "reason": "error", "error": msg})
                        stream.end(msg)
                        return
                    choice = (chunk.get("choices") or [{}])[0]
                    if not isinstance(choice, dict):
                        msg = error_message(model, "Invalid SSE choice frame")
                        stream.push({"type": "error", "reason": "error", "error": msg})
                        stream.end(msg)
                        return
                    delta = choice.get("delta") or {}
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
                    if "content" in delta and delta["content"]:
                        if text_index is None:
                            text_index = len(partial["content"])
                            partial["content"] = [
                                *partial["content"],
                                {"type": "text", "text": ""},
                            ]
                            stream.push(
                                {
                                    "type": "text_start",
                                    "contentIndex": text_index,
                                    "partial": _clone(partial),
                                }
                            )
                        partial["content"][text_index]["text"] += delta["content"]  # type: ignore[index]
                        stream.push(
                            {
                                "type": "text_delta",
                                "contentIndex": text_index,
                                "delta": delta["content"],
                                "partial": _clone(partial),
                            }
                        )
                    for tc in delta.get("tool_calls") or []:
                        idx = int(tc.get("index") or 0)
                        buf = tool_buffers.setdefault(
                            idx,
                            {"id": tc.get("id") or f"call_{idx}", "name": "", "arguments": ""},
                        )
                        if tc.get("id"):
                            buf["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            buf["name"] = fn["name"]
                        if fn.get("arguments"):
                            buf["arguments"] += fn["arguments"]
                        # emit start once and keep the partial tool block current
                        content_index = None
                        for i, block in enumerate(partial["content"]):
                            if block.get("type") == "toolCall" and block.get("id") == buf["id"]:
                                content_index = i
                                break
                        if content_index is None:
                            content_index = len(partial["content"])
                            partial["content"] = [
                                *partial["content"],
                                {
                                    "type": "toolCall",
                                    "id": buf["id"],
                                    "name": buf["name"] or "",
                                    "arguments": {},
                                },
                            ]
                            stream.push(
                                {
                                    "type": "toolcall_start",
                                    "contentIndex": content_index,
                                    "partial": _clone(partial),
                                }
                            )
                        block = partial["content"][content_index]
                        if fn.get("name"):
                            block["name"] = buf["name"]
                        if fn.get("arguments"):
                            parsed_args = parse_partial_json(buf["arguments"])
                            if isinstance(parsed_args, dict):
                                block["arguments"] = parsed_args
                            stream.push(
                                {
                                    "type": "toolcall_delta",
                                    "contentIndex": content_index,
                                    "delta": fn["arguments"],
                                    "partial": _clone(partial),
                                }
                            )
                    usage = chunk.get("usage")
                    if usage:
                        partial["usage"].update(_openai_usage(usage))

        # finalize text
        if text_index is not None:
            text = partial["content"][text_index].get("text") or ""  # type: ignore[union-attr]
            stream.push(
                {
                    "type": "text_end",
                    "contentIndex": text_index,
                    "content": text,
                    "partial": _clone(partial),
                }
            )

        # finalize tools
        for idx, buf in tool_buffers.items():
            content_index = next(
                (
                    i
                    for i, b in enumerate(partial["content"])
                    if b.get("type") == "toolCall" and b.get("id") == buf["id"]
                ),
                None,
            )
            if content_index is None:
                continue
            args = parse_partial_json(buf["arguments"])
            tool_call: ToolCall = {
                "type": "toolCall",
                "id": buf["id"],
                "name": buf["name"],
                "arguments": args if isinstance(args, dict) else {},
            }
            partial["content"][content_index] = tool_call
            stream.push(
                {
                    "type": "toolcall_end",
                    "contentIndex": content_index,
                    "toolCall": tool_call,
                    "partial": _clone(partial),
                }
            )

        stop = "toolUse" if tool_buffers else _map_finish(finish_reason)
        partial["stopReason"] = stop  # type: ignore[typeddict-item]
        if stop in ("error", "aborted"):
            stream.push({"type": "error", "reason": stop, "error": partial})  # type: ignore[arg-type]
            stream.end(partial)
            return
        stream.push({"type": "done", "reason": stop, "message": partial})  # type: ignore[arg-type]
        stream.end(partial)

    return await run_setup_stream(model, runner)


def _openai_usage(raw: dict[str, Any]) -> dict[str, int]:
    prompt = int(raw.get("prompt_tokens") or 0)
    details = raw.get("prompt_tokens_details") or {}
    cache_read = int(details.get("cached_tokens") or raw.get("prompt_cache_hit_tokens") or 0)
    cache_write = int(details.get("cache_write_tokens") or 0)
    output = int(raw.get("completion_tokens") or 0)
    input_tokens = max(0, prompt - cache_read - cache_write)
    return {
        "input": input_tokens,
        "output": output,
        "cacheRead": cache_read,
        "cacheWrite": cache_write,
        "totalTokens": input_tokens + output + cache_read + cache_write,
    }


def _map_finish(reason: str) -> str:
    if reason in ("tool_calls", "function_call"):
        return "toolUse"
    if reason == "length":
        return "length"
    return "stop"


def _clone(msg: AssistantMessage) -> AssistantMessage:
    return json.loads(json.dumps(msg))


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value
