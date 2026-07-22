"""Provider factory for groq — isomorphic to providers/groq.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .groq_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api

def groq_provider() -> Provider:
    return create_provider({
        "id": "groq",
        "name": "Groq",
        "baseUrl": "https://api.groq.com/openai/v1",
        "auth": {"apiKey": env_api_key_auth("Groq API key", ["GROQ_API_KEY"])},
        "models": get_models(),
        "api": open_ai_completions_api(),
    })

groqProvider = groq_provider
