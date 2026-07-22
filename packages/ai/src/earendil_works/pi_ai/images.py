"""Image generation entrypoints."""
from __future__ import annotations
from typing import Any
from .api.openrouter_images import generate_images
from .types import ImagesContext, Model

async def generate(model: Model, context: ImagesContext, options: dict[str, Any] | None = None):
    return await generate_images(model, context, options)
