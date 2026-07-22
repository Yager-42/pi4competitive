"""Provider factory for cloudflare-ai-gateway — isomorphic to providers/cloudflare-ai-gateway.ts."""
from __future__ import annotations

async def _ambient_resolve(_args):
    return {"auth": {}, "source": "ambient"}

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .cloudflare_ai_gateway_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api
from earendil_works.pi_ai.api.openai_responses import open_ai_responses_api
from earendil_works.pi_ai.api.anthropic_messages import anthropic_messages_api

def cloudflare_ai_gateway_provider() -> Provider:
    return create_provider({
        "id": "cloudflare-ai-gateway",
        "name": "Cloudflare AI Gateway",
        "auth": {"apiKey": {"name": "ambient", "resolve": _ambient_resolve}},
        "models": get_models(),
        "api": {
            "openai-completions": open_ai_completions_api(),
            "openai-responses": open_ai_responses_api(),
            "anthropic-messages": anthropic_messages_api()
        },
    })

cloudflare_ai_gatewayProvider = cloudflare_ai_gateway_provider
