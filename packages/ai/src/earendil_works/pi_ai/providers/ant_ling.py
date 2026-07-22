"""Provider factory for ant-ling — isomorphic to providers/ant-ling.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .ant_ling_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api

def ant_ling_provider() -> Provider:
    return create_provider({
        "id": "ant-ling",
        "name": "Ant Ling",
        "auth": {"apiKey": env_api_key_auth("Ant Ling API key", ["ANT_LING_API_KEY"])},
        "models": get_models(),
        "api": open_ai_completions_api(),
    })

ant_lingProvider = ant_ling_provider
