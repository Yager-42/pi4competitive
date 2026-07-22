"""Provider factory for vercel-ai-gateway — isomorphic to providers/vercel-ai-gateway.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .vercel_ai_gateway_models import get_models
from earendil_works.pi_ai.api.anthropic_messages import anthropic_messages_api

def vercel_ai_gateway_provider() -> Provider:
    return create_provider({
        "id": "vercel-ai-gateway",
        "name": "Vercel AI Gateway",
        "auth": {"apiKey": env_api_key_auth("Vercel AI Gateway API key", ["AI_GATEWAY_API_KEY"])},
        "models": get_models(),
        "api": anthropic_messages_api(),
    })

vercel_ai_gatewayProvider = vercel_ai_gateway_provider
