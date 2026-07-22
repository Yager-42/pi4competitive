"""openai prompt cache helpers."""
from __future__ import annotations

def cache_retention_header(retention: str | None) -> dict[str, str]:
    if not retention or retention == "none":
        return {}
    return {"x-pi-cache-retention": retention}
