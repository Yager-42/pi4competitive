"""Message transform helpers — port intent of api/transform-messages.ts."""

from __future__ import annotations

from typing import Any

from ..types import Context, Message
from ..utils.text import extract_text


def context_to_openai_messages(context: Context) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if context.get("systemPrompt"):
        messages.append({"role": "system", "content": context["systemPrompt"]})
    for msg in context.get("messages") or []:
        role = msg.get("role")
        if role == "user":
            messages.append({"role": "user", "content": _user_content(msg)})
        elif role == "assistant":
            content_parts = []
            tool_calls = []
            for block in msg.get("content") or []:
                if block.get("type") == "text":
                    content_parts.append(block.get("text") or "")
                elif block.get("type") == "toolCall":
                    tool_calls.append(
                        {
                            "id": block.get("id"),
                            "type": "function",
                            "function": {
                                "name": block.get("name"),
                                "arguments": __import__("json").dumps(block.get("arguments") or {}),
                            },
                        }
                    )
            entry: dict[str, Any] = {"role": "assistant", "content": "\n".join(content_parts) or None}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            messages.append(entry)
        elif role == "toolResult":
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.get("toolCallId"),
                    "content": extract_text(msg.get("content")),
                }
            )
    return messages


def tools_to_openai(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description") or "",
                "parameters": t.get("parameters") or {"type": "object", "properties": {}},
            },
        }
        for t in tools
    ]


def context_to_anthropic_messages(context: Context) -> tuple[str | None, list[dict[str, Any]]]:
    system = context.get("systemPrompt")
    messages: list[dict[str, Any]] = []
    for msg in context.get("messages") or []:
        role = msg.get("role")
        if role == "user":
            messages.append({"role": "user", "content": _user_content(msg)})
        elif role == "assistant":
            content = []
            for block in msg.get("content") or []:
                if block.get("type") == "text":
                    content.append({"type": "text", "text": block.get("text") or ""})
                elif block.get("type") == "thinking":
                    content.append({"type": "thinking", "thinking": block.get("thinking") or ""})
                elif block.get("type") == "toolCall":
                    content.append(
                        {
                            "type": "tool_use",
                            "id": block.get("id"),
                            "name": block.get("name"),
                            "input": block.get("arguments") or {},
                        }
                    )
            messages.append({"role": "assistant", "content": content})
        elif role == "toolResult":
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.get("toolCallId"),
                            "content": extract_text(msg.get("content")),
                            "is_error": bool(msg.get("isError")),
                        }
                    ],
                }
            )
    return system, messages


def tools_to_anthropic(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "name": t["name"],
            "description": t.get("description") or "",
            "input_schema": t.get("parameters") or {"type": "object", "properties": {}},
        }
        for t in tools
    ]


def _user_content(msg: Message) -> Any:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if block.get("type") == "text":
            parts.append({"type": "text", "text": block.get("text") or ""})
        elif block.get("type") == "image":
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{block.get('mimeType')};base64,{block.get('data')}",
                    },
                }
            )
    return parts if parts else ""


def build_openai_completions_payload(
    model: dict[str, Any],
    context: Context,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = options or {}
    payload: dict[str, Any] = {
        "model": model["id"],
        "messages": context_to_openai_messages(context),
        "stream": True,
    }
    retention = options.get("cacheRetention", "short")
    compat = model.get("compat") or {}
    supports_long = bool(compat.get("supportsLongCacheRetention"))
    if options.get("sessionId") and (
        ("api.openai.com" in (model.get("baseUrl") or "") and retention != "none")
        or (retention == "long" and supports_long)
    ):
        payload["prompt_cache_key"] = options["sessionId"][:64]
    if retention == "long" and supports_long:
        payload["prompt_cache_retention"] = "24h"
    if options.get("temperature") is not None:
        payload["temperature"] = options["temperature"]
    if options.get("maxTokens") is not None:
        payload["max_tokens"] = options["maxTokens"]
    tools = tools_to_openai(context.get("tools"))  # type: ignore[arg-type]
    if tools:
        payload["tools"] = tools
    return payload


def build_anthropic_messages_payload(
    model: dict[str, Any],
    context: Context,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = options or {}
    system, messages = context_to_anthropic_messages(context)
    payload: dict[str, Any] = {
        "model": model["id"],
        "messages": messages,
        "max_tokens": options.get("maxTokens") or model.get("maxTokens") or 4096,
        "stream": True,
    }
    if system:
        payload["system"] = system
    if options.get("temperature") is not None:
        payload["temperature"] = options["temperature"]
    tools = tools_to_anthropic(context.get("tools"))  # type: ignore[arg-type]
    if tools:
        payload["tools"] = tools
    return payload
