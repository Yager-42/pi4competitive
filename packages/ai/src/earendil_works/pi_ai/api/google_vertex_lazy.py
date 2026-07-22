"""Lazy loader for google_vertex."""
from __future__ import annotations
from typing import Any
from .lazy import lazy_api

def google_vertex_api() -> dict[str, Any]:
    async def load():
        from .google_vertex import google_vertex_api
        return google_vertex_api()
    # eager for Python (import cheap); still match lazyApi surface
    from .google_vertex import google_vertex_api
    return google_vertex_api()
