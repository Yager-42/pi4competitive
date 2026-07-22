"""Provider factory for fireworks — isomorphic to providers/fireworks.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .fireworks_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api
from earendil_works.pi_ai.api.anthropic_messages import anthropic_messages_api

def fireworks_provider() -> Provider:
    return create_provider({
        "id": "fireworks",
        "name": "Fireworks",
        "auth": {"apiKey": env_api_key_auth("Fireworks API key", ["FIREWORKS_API_KEY"])},
        "models": get_models(),
        "api": {
            "openai-completions": open_ai_completions_api(),
            "anthropic-messages": anthropic_messages_api()
        },
    })

fireworksProvider = fireworks_provider
