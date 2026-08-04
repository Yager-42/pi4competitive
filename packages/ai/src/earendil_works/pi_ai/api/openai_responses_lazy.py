"""Lazy loader for openai_responses."""
from __future__ import annotations
from typing import Any
from .lazy import lazy_api

def openai_responses_api() -> dict[str, Any]:
    async def load():
        from .openai_responses import open_ai_responses_api
        return open_ai_responses_api()
    return lazy_api(load)
