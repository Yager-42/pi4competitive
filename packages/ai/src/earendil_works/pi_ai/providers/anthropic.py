"""Provider factory for anthropic — isomorphic to providers/anthropic.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .anthropic_models import get_models
from earendil_works.pi_ai.api.anthropic_messages import anthropic_messages_api

def anthropic_provider() -> Provider:
    return create_provider({
        "id": "anthropic",
        "name": "Anthropic",
        "baseUrl": "https://api.anthropic.com",
        "auth": {"apiKey": env_api_key_auth("Anthropic API key", ["ANTHROPIC_OAUTH_TOKEN", "ANTHROPIC_API_KEY"])},
        "models": get_models(),
        "api": anthropic_messages_api(),
    })

anthropicProvider = anthropic_provider
