"""Provider factory for minimax — isomorphic to providers/minimax.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .minimax_models import get_models
from earendil_works.pi_ai.api.anthropic_messages import anthropic_messages_api

def minimax_provider() -> Provider:
    return create_provider({
        "id": "minimax",
        "name": "MiniMax",
        "auth": {"apiKey": env_api_key_auth("MiniMax API key", ["MINIMAX_API_KEY"])},
        "models": get_models(),
        "api": anthropic_messages_api(),
    })

minimaxProvider = minimax_provider
