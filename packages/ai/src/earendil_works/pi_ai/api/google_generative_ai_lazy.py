"""Lazy loader for google_generative_ai."""
from __future__ import annotations
from typing import Any
from .lazy import lazy_api

def google_generative_ai_api() -> dict[str, Any]:
    async def load():
        from .google_generative_ai import google_generative_ai_api
        return google_generative_ai_api()
    # eager for Python (import cheap); still match lazyApi surface
    from .google_generative_ai import google_generative_ai_api
    return google_generative_ai_api()
