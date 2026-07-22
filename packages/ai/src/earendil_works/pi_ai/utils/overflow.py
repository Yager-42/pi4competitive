"""Context overflow helpers."""

from __future__ import annotations


def estimate_tokens_from_text(text: str) -> int:
    return max(1, (len(text) + 3) // 4)
