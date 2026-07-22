"""Provider factory for github-copilot — isomorphic to providers/github-copilot.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .github_copilot_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api
from earendil_works.pi_ai.api.openai_responses import open_ai_responses_api
from earendil_works.pi_ai.api.anthropic_messages import anthropic_messages_api

def github_copilot_provider() -> Provider:
    return create_provider({
        "id": "github-copilot",
        "name": "GitHub Copilot",
        "auth": {"apiKey": env_api_key_auth("GitHub Copilot API key", ["COPILOT_GITHUB_TOKEN"])},
        "models": get_models(),
        "api": {
            "openai-completions": open_ai_completions_api(),
            "openai-responses": open_ai_responses_api(),
            "anthropic-messages": anthropic_messages_api()
        },
    })

github_copilotProvider = github_copilot_provider
