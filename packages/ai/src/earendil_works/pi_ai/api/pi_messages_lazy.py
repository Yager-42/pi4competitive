"""Lazy loader for pi_messages."""
from __future__ import annotations
from typing import Any
from .lazy import lazy_api

def pi_messages_api() -> dict[str, Any]:
    async def load():
        from .pi_messages import pi_messages_api
        return pi_messages_api()
    # eager for Python (import cheap); still match lazyApi surface
    from .pi_messages import pi_messages_api
    return pi_messages_api()
