"""Lazy loader for openai_completions."""
from __future__ import annotations
from typing import Any
from .lazy import lazy_api

def openai_completions_api() -> dict[str, Any]:
    async def load():
        from .openai_completions import open_ai_completions_api
        return open_ai_completions_api()
    # eager for Python (import cheap); still match lazyApi surface
    from .openai_completions import open_ai_completions_api
    return open_ai_completions_api()
