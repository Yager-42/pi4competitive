"""Shared Google convert helpers."""
from __future__ import annotations
from typing import Any
from ..types import Context

def convert_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "function_declarations": [
                {
                    "name": t["name"],
                    "description": t.get("description") or "",
                    "parameters": t.get("parameters") or {"type": "object", "properties": {}},
                }
                for t in tools
            ]
        }
    ]

def context_to_google_contents(context: Context) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    for msg in context.get("messages") or []:
        role = msg.get("role")
        if role == "toolResult":
            text = " ".join(
                b.get("text", "")
                for b in (msg.get("content") or [])
                if isinstance(b, dict) and b.get("type") == "text"
            )
            response_key = "error" if msg.get("isError") else "result"
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": msg.get("toolName") or "",
                                "response": {response_key: text},
                            }
                        }
                    ],
                }
            )
            continue

        role_name = "user" if role == "user" else "model"
        parts: list[dict[str, Any]] = []
        if role == "user":
            content = msg.get("content")
            if isinstance(content, str):
                parts.append({"text": content})
            else:
                parts.extend(
                    {"text": b.get("text", "")}
                    for b in (content or [])
                    if isinstance(b, dict) and b.get("type") == "text"
                )
        elif role == "assistant":
            for block in msg.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    parts.append({"text": block.get("text", "")})
                elif block.get("type") == "toolCall":
                    call: dict[str, Any] = {
                        "name": block.get("name") or "",
                        "args": block.get("arguments") or {},
                    }
                    if block.get("thoughtSignature"):
                        call["thoughtSignature"] = block["thoughtSignature"]
                    parts.append({"functionCall": call})
        if not parts:
            parts = [{"text": ""}]
        contents.append({"role": role_name, "parts": parts})
    return contents
