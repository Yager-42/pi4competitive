"""Provider factory for cerebras — isomorphic to providers/cerebras.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .cerebras_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api

def cerebras_provider() -> Provider:
    return create_provider({
        "id": "cerebras",
        "name": "Cerebras",
        "auth": {"apiKey": env_api_key_auth("Cerebras API key", ["CEREBRAS_API_KEY"])},
        "models": get_models(),
        "api": open_ai_completions_api(),
    })

cerebrasProvider = cerebras_provider
