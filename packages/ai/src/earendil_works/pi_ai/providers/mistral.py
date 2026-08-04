"""Provider factory for mistral — isomorphic to providers/mistral.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .mistral_models import get_models
from earendil_works.pi_ai.api.mistral_conversations import mistral_conversations_api

def _normalize_base_url(base_url: str | None) -> str:
    normalized = (base_url or "https://api.mistral.ai").rstrip("/")
    return normalized if normalized.endswith("/v1") else f"{normalized}/v1"


def mistral_provider() -> Provider:
    models = [
        {**model, "baseUrl": _normalize_base_url(model.get("baseUrl"))}
        for model in get_models()
    ]
    return create_provider({
        "id": "mistral",
        "name": "Mistral",
        "auth": {"apiKey": env_api_key_auth("Mistral API key", ["MISTRAL_API_KEY"])},
        "models": models,
        "api": mistral_conversations_api(),
    })

mistralProvider = mistral_provider
