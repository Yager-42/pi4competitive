"""JSON Schema validation helpers (TypeBox → JSON Schema)."""

from __future__ import annotations

from typing import Any


class ValidationError(ValueError):
    def __init__(self, message: str, path: str = "") -> None:
        super().__init__(message)
        self.path = path


def validate_tool_arguments(parameters: dict[str, Any] | None, arguments: dict[str, Any]) -> dict[str, Any]:
    """Lightweight required-properties check against a JSON Schema-like object."""
    if not parameters:
        return arguments
    if parameters.get("type") == "object" or "properties" in parameters:
        props = parameters.get("properties") or {}
        required = parameters.get("required") or []
        for key in required:
            if key not in arguments:
                raise ValidationError(f"Missing required property: {key}", path=key)
        if parameters.get("additionalProperties") is False:
            for key in arguments:
                if key not in props:
                    raise ValidationError(f"Unexpected property: {key}", path=key)
    return arguments
