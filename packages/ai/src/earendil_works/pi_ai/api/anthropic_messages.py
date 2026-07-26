"""anthropic-messages API — port of api/anthropic-messages.ts stream surface."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from ..types import AssistantMessage, Context, Model, SimpleStreamOptions, StreamOptions, empty_usage
from ..utils.event_stream import AssistantMessageEventStream, create_assistant_message_event_stream
from ..utils.json_parse import parse_partial_json
from .transform_messages import build_anthropic_messages_payload
from ._http_stream import error_message, is_aborted


def stream(
    model: Model,
    context: Context,
    options: StreamOptions | None = None,
) -> AssistantMessageEventStream:
    outer = create_assistant_message_event_stream()

    async def run() -> None:
        if is_aborted(options):
            msg = error_message(model, "aborted", aborted=True)
            outer.push({"type": "error", "reason": "aborted", "error": msg})
            outer.end(msg)
            return
        api_key = (options or {}).get("apiKey")
        if not api_key:
            msg = error_message(model, "Missing API key")
            outer.push({"type": "error", "reason": "error", "error": msg})
            outer.end(msg)
            return

        payload = build_anthropic_messages_payload(model, context, options)  # type: ignore[arg-type]
        on_payload = (options or {}).get("onPayload")
        if on_payload:
            replaced = on_payload(payload, model)
            if hasattr(replaced, "__await__"):
                replaced = await replaced
            if replaced is not None:
                payload = replaced

        base = model.get("baseUrl") or "https://api.anthropic.com"
        url = f"{base.rstrip('/')}/v1/messages"
        headers = {
            "x-api-key": str(api_key),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        for k, v in ((options or {}).get("headers") or {}).items():
            if v is not None:
                headers[k] = v

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
        outer.push({"type": "start", "partial": dict(partial)})
        block_index = -1
        tool_json = ""

        try:
            timeout = ((options or {}).get("timeoutMs") or 600_000) / 1000.0
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code >= 400:
                        text = (await resp.aread()).decode("utf-8", errors="replace")
                        msg = error_message(model, f"HTTP {resp.status_code}: {text[:500]}")
                        outer.push({"type": "error", "reason": "error", "error": msg})
                        outer.end(msg)
                        return
                    async for line in resp.aiter_lines():
                        if is_aborted(options):
                            msg = error_message(model, "aborted", aborted=True)
                            outer.push({"type": "error", "reason": "aborted", "error": msg})
                            outer.end(msg)
                            return
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data:
                            continue
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        et = event.get("type")
                        if et == "content_block_start":
                            block = event.get("content_block") or {}
                            block_index = int(event.get("index") or 0)
                            if block.get("type") == "text":
                                partial["content"] = [*partial["content"], {"type": "text", "text": ""}]
                                outer.push(
                                    {
                                        "type": "text_start",
                                        "contentIndex": block_index,
                                        "partial": json.loads(json.dumps(partial)),
                                    }
                                )
                            elif block.get("type") == "tool_use":
                                tool_json = ""
                                partial["content"] = [
                                    *partial["content"],
                                    {
                                        "type": "toolCall",
                                        "id": block.get("id") or f"tool_{block_index}",
                                        "name": block.get("name") or "",
                                        "arguments": {},
                                    },
                                ]
                                outer.push(
                                    {
                                        "type": "toolcall_start",
                                        "contentIndex": block_index,
                                        "partial": json.loads(json.dumps(partial)),
                                    }
                                )
                            elif block.get("type") == "thinking":
                                partial["content"] = [
                                    *partial["content"],
                                    {"type": "thinking", "thinking": ""},
                                ]
                                outer.push(
                                    {
                                        "type": "thinking_start",
                                        "contentIndex": block_index,
                                        "partial": json.loads(json.dumps(partial)),
                                    }
                                )
                        elif et == "content_block_delta":
                            delta = event.get("delta") or {}
                            if delta.get("type") == "text_delta":
                                text = delta.get("text") or ""
                                partial["content"][block_index]["text"] += text  # type: ignore[index]
                                outer.push(
                                    {
                                        "type": "text_delta",
                                        "contentIndex": block_index,
                                        "delta": text,
                                        "partial": json.loads(json.dumps(partial)),
                                    }
                                )
                            elif delta.get("type") == "input_json_delta":
                                piece = delta.get("partial_json") or ""
                                tool_json += piece
                                outer.push(
                                    {
                                        "type": "toolcall_delta",
                                        "contentIndex": block_index,
                                        "delta": piece,
                                        "partial": json.loads(json.dumps(partial)),
                                    }
                                )
                            elif delta.get("type") == "thinking_delta":
                                thinking = delta.get("thinking") or ""
                                partial["content"][block_index]["thinking"] += thinking  # type: ignore[index]
                                outer.push(
                                    {
                                        "type": "thinking_delta",
                                        "contentIndex": block_index,
                                        "delta": thinking,
                                        "partial": json.loads(json.dumps(partial)),
                                    }
                                )
                        elif et == "content_block_stop":
                            block = partial["content"][block_index] if block_index >= 0 else None
                            if not block:
                                continue
                            if block.get("type") == "text":
                                outer.push(
                                    {
                                        "type": "text_end",
                                        "contentIndex": block_index,
                                        "content": block.get("text") or "",
                                        "partial": json.loads(json.dumps(partial)),
                                    }
                                )
                            elif block.get("type") == "toolCall":
                                args = parse_partial_json(tool_json)
                                block["arguments"] = args if isinstance(args, dict) else {}
                                outer.push(
                                    {
                                        "type": "toolcall_end",
                                        "contentIndex": block_index,
                                        "toolCall": block,  # type: ignore[typeddict-item]
                                        "partial": json.loads(json.dumps(partial)),
                                    }
                                )
                            elif block.get("type") == "thinking":
                                outer.push(
                                    {
                                        "type": "thinking_end",
                                        "contentIndex": block_index,
                                        "content": block.get("thinking") or "",
                                        "partial": json.loads(json.dumps(partial)),
                                    }
                                )
                        elif et in ("message_delta", "message_start"):
                            usage = (
                                event.get("usage")
                                if et == "message_delta"
                                else (event.get("message") or {}).get("usage")
                            ) or {}
                            if usage:
                                _apply_anthropic_usage(partial["usage"], usage)
                            if et == "message_delta":
                                stop_reason = (event.get("delta") or {}).get("stop_reason")
                                if stop_reason == "tool_use":
                                    partial["stopReason"] = "toolUse"
                                elif stop_reason == "max_tokens":
                                    partial["stopReason"] = "length"

            reason = partial["stopReason"] if partial["stopReason"] in ("stop", "length", "toolUse") else "stop"
            partial["stopReason"] = reason  # type: ignore[typeddict-item]
            outer.push({"type": "done", "reason": reason, "message": partial})  # type: ignore[arg-type]
            outer.end(partial)
        except Exception as exc:
            msg = error_message(model, exc)
            outer.push({"type": "error", "reason": "error", "error": msg})
            outer.end(msg)

    import asyncio

    try:
        asyncio.get_running_loop().create_task(run())
    except RuntimeError:
        pass
    return outer


def _apply_anthropic_usage(target: dict[str, Any], raw: dict[str, Any]) -> None:
    fields = {
        "input": "input_tokens",
        "output": "output_tokens",
        "cacheRead": "cache_read_input_tokens",
        "cacheWrite": "cache_creation_input_tokens",
    }
    for target_key, raw_key in fields.items():
        if raw.get(raw_key) is not None:
            target[target_key] = int(raw[raw_key])
    creation = raw.get("cache_creation") or {}
    if creation.get("ephemeral_1h_input_tokens") is not None:
        target["cacheWrite1h"] = int(creation["ephemeral_1h_input_tokens"])
    target["totalTokens"] = sum(int(target.get(k) or 0) for k in ("input", "output", "cacheRead", "cacheWrite"))


def stream_simple(
    model: Model,
    context: Context,
    options: SimpleStreamOptions | None = None,
) -> AssistantMessageEventStream:
    return stream(model, context, options)  # type: ignore[arg-type]


def anthropic_messages_api() -> dict[str, Any]:
    return {"stream": stream, "streamSimple": stream_simple, "stream_simple": stream_simple}


anthropicMessagesApi = anthropic_messages_api
