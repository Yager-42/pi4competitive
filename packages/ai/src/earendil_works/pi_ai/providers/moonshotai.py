"""Provider factory for moonshotai — isomorphic to providers/moonshotai.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .moonshotai_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api

def moonshotai_provider() -> Provider:
    return create_provider({
        "id": "moonshotai",
        "name": "Moonshot AI",
        "auth": {"apiKey": env_api_key_auth("Moonshot AI API key", ["MOONSHOT_API_KEY"])},
        "models": get_models(),
        "api": open_ai_completions_api(),
    })

moonshotaiProvider = moonshotai_provider
