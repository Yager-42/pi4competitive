"""Images API registry."""
from __future__ import annotations
from .api.openrouter_images import openrouter_images_api

def builtin_images_apis():
    return {"openrouter-images": openrouter_images_api()}
