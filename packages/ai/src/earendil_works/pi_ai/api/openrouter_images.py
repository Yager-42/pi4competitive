"""openrouter-images API module."""
from __future__ import annotations
import time
from typing import Any
from ..types import AssistantImages, ImagesContext, Model, empty_usage

async def generate_images(model: Model, context: ImagesContext, options: dict[str, Any] | None = None) -> AssistantImages:
    return {
        "api": model.get("api") or "openrouter-images",
        "provider": model.get("provider") or "openrouter",
        "model": model["id"],
        "output": [],
        "stopReason": "error",
        "errorMessage": "Image generation requires live API credentials",
        "usage": empty_usage(),
        "timestamp": int(time.time() * 1000),
    }

def openrouter_images_api() -> dict[str, Any]:
    return {"generate": generate_images}

openrouterImagesApi = openrouter_images_api
