"""OAuth host surface (no Bun)."""
from __future__ import annotations
from .auth.oauth.load import (
    load_anthropic_oauth,
    load_openrouter_oauth,
    load_radius_oauth,
    load_xai_oauth,
)
__all__ = [
    "load_anthropic_oauth",
    "load_openrouter_oauth",
    "load_radius_oauth",
    "load_xai_oauth",
]
