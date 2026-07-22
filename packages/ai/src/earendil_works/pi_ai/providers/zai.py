"""Provider factory for zai — isomorphic to providers/zai.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .zai_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api

def zai_provider() -> Provider:
    return create_provider({
        "id": "zai",
        "name": "ZAI",
        "auth": {"apiKey": env_api_key_auth("ZAI API key", ["ZAI_API_KEY"])},
        "models": get_models(),
        "api": open_ai_completions_api(),
    })

zaiProvider = zai_provider
