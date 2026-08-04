"""Diagnostics helpers (host-adapted)."""

from __future__ import annotations

from typing import Any


_SENSITIVE_KEYS = {
    "apikey", "accesstoken", "refreshtoken", "token", "secret", "password",
    "authorization", "cookie", "credential", "credentials", "auth", "email",
}


def _redact(value: Any, *, key: str | None = None) -> Any:
    if key is not None and "".join(ch for ch in key.lower() if ch.isalnum()) in _SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


def redacted_diagnostic(message: str, **extra: Any) -> dict[str, Any]:
    return {"message": message, **_redact(extra)}
