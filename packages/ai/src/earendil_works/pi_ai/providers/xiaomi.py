"""Provider factory for xiaomi — isomorphic to providers/xiaomi.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .xiaomi_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api

def xiaomi_provider() -> Provider:
    return create_provider({
        "id": "xiaomi",
        "name": "Xiaomi",
        "auth": {"apiKey": env_api_key_auth("Xiaomi API key", ["XIAOMI_API_KEY"])},
        "models": get_models(),
        "api": open_ai_completions_api(),
    })

xiaomiProvider = xiaomi_provider
