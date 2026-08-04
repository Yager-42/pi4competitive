"""Lazy loader for bedrock_converse_stream."""
from __future__ import annotations
from typing import Any
from .lazy import lazy_api

def bedrock_converse_stream_api() -> dict[str, Any]:
    async def load():
        from .bedrock_converse_stream import bedrock_converse_stream_api
        return bedrock_converse_stream_api()
    return lazy_api(load)
