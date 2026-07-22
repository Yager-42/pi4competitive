"""Provider factory for cloudflare-workers-ai — isomorphic to providers/cloudflare-workers-ai.ts."""
from __future__ import annotations

async def _ambient_resolve(_args):
    return {"auth": {}, "source": "ambient"}

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .cloudflare_workers_ai_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api

def cloudflare_workers_ai_provider() -> Provider:
    return create_provider({
        "id": "cloudflare-workers-ai",
        "name": "Cloudflare Workers AI",
        "auth": {"apiKey": {"name": "ambient", "resolve": _ambient_resolve}},
        "models": get_models(),
        "api": open_ai_completions_api(),
    })

cloudflare_workers_aiProvider = cloudflare_workers_ai_provider
