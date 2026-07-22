"""openai responses shared helpers."""
from __future__ import annotations
from typing import Any

def normalize_responses_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    return tools
