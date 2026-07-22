"""Provider factory for minimax-cn — isomorphic to providers/minimax-cn.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .minimax_cn_models import get_models
from earendil_works.pi_ai.api.anthropic_messages import anthropic_messages_api

def minimax_cn_provider() -> Provider:
    return create_provider({
        "id": "minimax-cn",
        "name": "MiniMax CN",
        "auth": {"apiKey": env_api_key_auth("MiniMax CN API key", ["MINIMAX_CN_API_KEY"])},
        "models": get_models(),
        "api": anthropic_messages_api(),
    })

minimax_cnProvider = minimax_cn_provider
