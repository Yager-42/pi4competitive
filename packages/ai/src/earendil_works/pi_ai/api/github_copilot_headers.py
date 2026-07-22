"""GitHub Copilot header helpers."""
from __future__ import annotations

def copilot_headers(token: str | None = None) -> dict[str, str]:
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}", "Editor-Version": "pi/0.1"}
