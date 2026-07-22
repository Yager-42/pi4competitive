"""Provider factory for together — isomorphic to providers/together.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .together_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api

def together_provider() -> Provider:
    return create_provider({
        "id": "together",
        "name": "Together",
        "auth": {"apiKey": env_api_key_auth("Together API key", ["TOGETHER_API_KEY"])},
        "models": get_models(),
        "api": open_ai_completions_api(),
    })

togetherProvider = together_provider
