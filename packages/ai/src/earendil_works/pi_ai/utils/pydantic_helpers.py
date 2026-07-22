"""TypeBox → Pydantic / JSON Schema helpers (host delta D21)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, create_model


def json_schema_to_pydantic(name: str, schema: dict[str, Any]) -> type[BaseModel]:
    """Build a loose Pydantic model from a JSON Schema object."""
    props = schema.get("properties") or {}
    fields: dict[str, Any] = {}
    required = set(schema.get("required") or [])
    for key, prop in props.items():
        typ: Any = Any
        t = prop.get("type") if isinstance(prop, dict) else None
        if t == "string":
            typ = str
        elif t == "integer":
            typ = int
        elif t == "number":
            typ = float
        elif t == "boolean":
            typ = bool
        if key in required:
            fields[key] = (typ, ...)
        else:
            fields[key] = (typ | None, None)
    return create_model(name, **fields)  # type: ignore[call-overload]
