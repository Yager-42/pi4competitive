"""Provider factory for xiaomi-token-plan-cn — isomorphic to providers/xiaomi-token-plan-cn.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .xiaomi_token_plan_cn_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api

def xiaomi_token_plan_cn_provider() -> Provider:
    return create_provider({
        "id": "xiaomi-token-plan-cn",
        "name": "Xiaomi Token Plan CN",
        "auth": {"apiKey": env_api_key_auth("Xiaomi Token Plan CN API key", ["XIAOMI_TOKEN_PLAN_CN_API_KEY"])},
        "models": get_models(),
        "api": open_ai_completions_api(),
    })

xiaomi_token_plan_cnProvider = xiaomi_token_plan_cn_provider
