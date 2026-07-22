"""Provider factory for openai-codex — isomorphic to providers/openai-codex.ts."""
from __future__ import annotations

async def _ambient_resolve(_args):
    return {"auth": {}, "source": "ambient"}

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .openai_codex_models import get_models
from earendil_works.pi_ai.api.openai_codex_responses import openai_codex_responses_api

def openai_codex_provider() -> Provider:
    return create_provider({
        "id": "openai-codex",
        "name": "OpenAI Codex",
        "auth": {"apiKey": {"name": "ambient", "resolve": _ambient_resolve}},
        "models": get_models(),
        "api": openai_codex_responses_api(),
    })

openai_codexProvider = openai_codex_provider
