"""Radius gateway provider (dynamic catalog)."""
from __future__ import annotations
from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from ..api.pi_messages import pi_messages_api

DEFAULT_RADIUS_GATEWAY = "https://api.radius.dev"

def radius_provider(options: dict | None = None) -> Provider:
    options = options or {}
    return create_provider({
        "id": options.get("id") or "radius",
        "name": options.get("name") or "Radius",
        "baseUrl": options.get("gateway") or DEFAULT_RADIUS_GATEWAY,
        "auth": {"apiKey": env_api_key_auth("Radius API key", ["RADIUS_API_KEY"])},
        "models": [],
        "api": pi_messages_api(),
    })

radiusProvider = radius_provider
