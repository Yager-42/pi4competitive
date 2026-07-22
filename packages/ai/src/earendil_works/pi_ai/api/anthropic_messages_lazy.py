"""Lazy loader for anthropic_messages."""
from __future__ import annotations
from typing import Any
from .lazy import lazy_api

def anthropic_messages_api() -> dict[str, Any]:
    async def load():
        from .anthropic_messages import anthropic_messages_api
        return anthropic_messages_api()
    # eager for Python (import cheap); still match lazyApi surface
    from .anthropic_messages import anthropic_messages_api
    return anthropic_messages_api()
