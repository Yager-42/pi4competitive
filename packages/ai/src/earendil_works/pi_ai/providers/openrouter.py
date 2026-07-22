"""Provider factory for openrouter — isomorphic to providers/openrouter.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .openrouter_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api

def openrouter_provider() -> Provider:
    return create_provider({
        "id": "openrouter",
        "name": "OpenRouter",
        "baseUrl": "https://openrouter.ai/api/v1",
        "auth": {"apiKey": env_api_key_auth("OpenRouter API key", ["OPENROUTER_API_KEY"])},
        "models": get_models(),
        "api": open_ai_completions_api(),
    })

openrouterProvider = openrouter_provider
