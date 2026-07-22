"""Provider factory for qwen-token-plan-cn — isomorphic to providers/qwen-token-plan-cn.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .qwen_token_plan_cn_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api

def qwen_token_plan_cn_provider() -> Provider:
    return create_provider({
        "id": "qwen-token-plan-cn",
        "name": "Qwen Token Plan CN",
        "auth": {"apiKey": env_api_key_auth("Qwen Token Plan CN API key", ["QWEN_TOKEN_PLAN_CN_API_KEY"])},
        "models": get_models(),
        "api": open_ai_completions_api(),
    })

qwen_token_plan_cnProvider = qwen_token_plan_cn_provider
