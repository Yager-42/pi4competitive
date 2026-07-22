"""Provider factory for azure-openai-responses — isomorphic to providers/azure-openai-responses.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .azure_openai_responses_models import get_models
from earendil_works.pi_ai.api.azure_openai_responses import azure_openai_responses_api

def azure_openai_responses_provider() -> Provider:
    return create_provider({
        "id": "azure-openai-responses",
        "name": "Azure OpenAI Responses",
        "auth": {"apiKey": env_api_key_auth("Azure OpenAI Responses API key", ["AZURE_OPENAI_API_KEY"])},
        "models": get_models(),
        "api": azure_openai_responses_api(),
    })

azure_openai_responsesProvider = azure_openai_responses_provider
