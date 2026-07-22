"""Provider factory for nvidia — isomorphic to providers/nvidia.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .nvidia_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api

def nvidia_provider() -> Provider:
    return create_provider({
        "id": "nvidia",
        "name": "NVIDIA",
        "auth": {"apiKey": env_api_key_auth("NVIDIA API key", ["NVIDIA_API_KEY"])},
        "models": get_models(),
        "api": open_ai_completions_api(),
    })

nvidiaProvider = nvidia_provider
