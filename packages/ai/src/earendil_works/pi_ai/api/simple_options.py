"""simple-options helpers."""
from __future__ import annotations
from typing import Any

def apply_simple_options(options: dict[str, Any] | None) -> dict[str, Any]:
    return dict(options or {})
