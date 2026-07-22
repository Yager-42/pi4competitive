"""Provider factory for xiaomi-token-plan-sgp — isomorphic to providers/xiaomi-token-plan-sgp.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .xiaomi_token_plan_sgp_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api

def xiaomi_token_plan_sgp_provider() -> Provider:
    return create_provider({
        "id": "xiaomi-token-plan-sgp",
        "name": "Xiaomi Token Plan SGP",
        "auth": {"apiKey": env_api_key_auth("Xiaomi Token Plan SGP API key", ["XIAOMI_TOKEN_PLAN_SGP_API_KEY"])},
        "models": get_models(),
        "api": open_ai_completions_api(),
    })

xiaomi_token_plan_sgpProvider = xiaomi_token_plan_sgp_provider
