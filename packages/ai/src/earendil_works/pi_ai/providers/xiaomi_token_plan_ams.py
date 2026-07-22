"""Provider factory for xiaomi-token-plan-ams — isomorphic to providers/xiaomi-token-plan-ams.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .xiaomi_token_plan_ams_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api

def xiaomi_token_plan_ams_provider() -> Provider:
    return create_provider({
        "id": "xiaomi-token-plan-ams",
        "name": "Xiaomi Token Plan AMS",
        "auth": {"apiKey": env_api_key_auth("Xiaomi Token Plan AMS API key", ["XIAOMI_TOKEN_PLAN_AMS_API_KEY"])},
        "models": get_models(),
        "api": open_ai_completions_api(),
    })

xiaomi_token_plan_amsProvider = xiaomi_token_plan_ams_provider
