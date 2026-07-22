"""Diagnostics helpers (host-adapted)."""

from __future__ import annotations

from typing import Any


def redacted_diagnostic(message: str, **extra: Any) -> dict[str, Any]:
    return {"message": message, **extra}
