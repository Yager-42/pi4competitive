"""Provider factory for openai — isomorphic to providers/openai.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .openai_models import get_models
from earendil_works.pi_ai.api.openai_responses import open_ai_responses_api

def openai_provider() -> Provider:
    return create_provider({
        "id": "openai",
        "name": "OpenAI",
        "baseUrl": "https://api.openai.com/v1",
        "auth": {"apiKey": env_api_key_auth("OpenAI API key", ["OPENAI_API_KEY"])},
        "models": get_models(),
        "api": open_ai_responses_api(),
    })

openaiProvider = openai_provider
