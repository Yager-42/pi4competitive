"""Lazy loader for azure_openai_responses."""
from __future__ import annotations
from typing import Any
from .lazy import lazy_api

def azure_openai_responses_api() -> dict[str, Any]:
    async def load():
        from .azure_openai_responses import azure_openai_responses_api
        return azure_openai_responses_api()
    # eager for Python (import cheap); still match lazyApi surface
    from .azure_openai_responses import azure_openai_responses_api
    return azure_openai_responses_api()
