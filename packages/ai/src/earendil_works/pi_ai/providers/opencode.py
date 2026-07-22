"""Provider factory for opencode — isomorphic to providers/opencode.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .opencode_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api
from earendil_works.pi_ai.api.openai_responses import open_ai_responses_api
from earendil_works.pi_ai.api.anthropic_messages import anthropic_messages_api
from earendil_works.pi_ai.api.google_generative_ai import google_generative_ai_api

def opencode_provider() -> Provider:
    return create_provider({
        "id": "opencode",
        "name": "OpenCode",
        "auth": {"apiKey": env_api_key_auth("OpenCode API key", ["OPENCODE_API_KEY"])},
        "models": get_models(),
        "api": {
            "openai-completions": open_ai_completions_api(),
            "openai-responses": open_ai_responses_api(),
            "anthropic-messages": anthropic_messages_api(),
            "google-generative-ai": google_generative_ai_api()
        },
    })

opencodeProvider = opencode_provider
