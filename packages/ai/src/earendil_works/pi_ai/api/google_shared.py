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
    contents = []
    for msg in context.get("messages") or []:
        role = "user" if msg.get("role") in ("user", "toolResult") else "model"
        text = ""
        if msg.get("role") == "user":
            c = msg.get("content")
            text = c if isinstance(c, str) else " ".join(
                b.get("text","") for b in (c or []) if isinstance(b, dict) and b.get("type")=="text"
            )
        elif msg.get("role") == "assistant":
            text = " ".join(
                b.get("text","") for b in (msg.get("content") or []) if isinstance(b, dict) and b.get("type")=="text"
            )
        contents.append({"role": role, "parts": [{"text": text}]})
    return contents
