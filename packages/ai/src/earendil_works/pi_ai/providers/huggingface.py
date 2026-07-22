"""Provider factory for huggingface — isomorphic to providers/huggingface.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .huggingface_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api

def huggingface_provider() -> Provider:
    return create_provider({
        "id": "huggingface",
        "name": "Hugging Face",
        "auth": {"apiKey": env_api_key_auth("Hugging Face API key", ["HF_TOKEN"])},
        "models": get_models(),
        "api": open_ai_completions_api(),
    })

huggingfaceProvider = huggingface_provider
