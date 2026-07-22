"""Provider factory for kimi-coding — isomorphic to providers/kimi-coding.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .kimi_coding_models import get_models
from earendil_works.pi_ai.api.anthropic_messages import anthropic_messages_api

def kimi_coding_provider() -> Provider:
    return create_provider({
        "id": "kimi-coding",
        "name": "Kimi Coding",
        "auth": {"apiKey": env_api_key_auth("Kimi Coding API key", ["KIMI_API_KEY"])},
        "models": get_models(),
        "api": anthropic_messages_api(),
    })

kimi_codingProvider = kimi_coding_provider
