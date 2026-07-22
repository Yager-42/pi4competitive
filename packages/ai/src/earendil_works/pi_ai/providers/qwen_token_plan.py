"""Provider factory for qwen-token-plan — isomorphic to providers/qwen-token-plan.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .qwen_token_plan_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api

def qwen_token_plan_provider() -> Provider:
    return create_provider({
        "id": "qwen-token-plan",
        "name": "Qwen Token Plan",
        "auth": {"apiKey": env_api_key_auth("Qwen Token Plan API key", ["QWEN_TOKEN_PLAN_API_KEY"])},
        "models": get_models(),
        "api": open_ai_completions_api(),
    })

qwen_token_planProvider = qwen_token_plan_provider
