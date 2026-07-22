"""Provider factory for zai-coding-cn — isomorphic to providers/zai-coding-cn.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .zai_coding_cn_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api

def zai_coding_cn_provider() -> Provider:
    return create_provider({
        "id": "zai-coding-cn",
        "name": "ZAI Coding CN",
        "auth": {"apiKey": env_api_key_auth("ZAI Coding CN API key", ["ZAI_CODING_CN_API_KEY"])},
        "models": get_models(),
        "api": open_ai_completions_api(),
    })

zai_coding_cnProvider = zai_coding_cn_provider
