"""Provider factory for xai — isomorphic to providers/xai.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .xai_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api
from earendil_works.pi_ai.api.openai_responses import open_ai_responses_api

def xai_provider() -> Provider:
    return create_provider({
        "id": "xai",
        "name": "xAI",
        "baseUrl": "https://api.x.ai/v1",
        "auth": {"apiKey": env_api_key_auth("xAI API key", ["XAI_API_KEY"])},
        "models": get_models(),
        "api": {
            "openai-completions": open_ai_completions_api(),
            "openai-responses": open_ai_responses_api()
        },
    })

xaiProvider = xai_provider
