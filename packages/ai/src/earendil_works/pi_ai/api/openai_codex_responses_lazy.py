"""Lazy loader for openai_codex_responses."""
from __future__ import annotations
from typing import Any
from .lazy import lazy_api

def openai_codex_responses_api() -> dict[str, Any]:
    async def load():
        from .openai_codex_responses import openai_codex_responses_api
        return openai_codex_responses_api()
    # eager for Python (import cheap); still match lazyApi surface
    from .openai_codex_responses import openai_codex_responses_api
    return openai_codex_responses_api()
