"""Provider factory for deepseek — isomorphic to providers/deepseek.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .deepseek_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api

def deepseek_provider() -> Provider:
    return create_provider({
        "id": "deepseek",
        "name": "DeepSeek",
        "baseUrl": "https://api.deepseek.com",
        "auth": {"apiKey": env_api_key_auth("DeepSeek API key", ["DEEPSEEK_API_KEY"])},
        "models": get_models(),
        "api": open_ai_completions_api(),
    })

deepseekProvider = deepseek_provider
