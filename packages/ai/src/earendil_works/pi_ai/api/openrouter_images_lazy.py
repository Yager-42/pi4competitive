"""Lazy loader for openrouter_images."""
from __future__ import annotations
from typing import Any
from .lazy import lazy_api

def openrouter_images_api() -> dict[str, Any]:
    async def load():
        from .openrouter_images import openrouter_images_api
        return openrouter_images_api()
    # eager for Python (import cheap); still match lazyApi surface
    from .openrouter_images import openrouter_images_api
    return openrouter_images_api()
