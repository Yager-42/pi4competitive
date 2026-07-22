"""Lazy loader for mistral_conversations."""
from __future__ import annotations
from typing import Any
from .lazy import lazy_api

def mistral_conversations_api() -> dict[str, Any]:
    async def load():
        from .mistral_conversations import mistral_conversations_api
        return mistral_conversations_api()
    # eager for Python (import cheap); still match lazyApi surface
    from .mistral_conversations import mistral_conversations_api
    return mistral_conversations_api()
