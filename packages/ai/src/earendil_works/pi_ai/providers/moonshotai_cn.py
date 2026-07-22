"""Provider factory for moonshotai-cn — isomorphic to providers/moonshotai-cn.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .moonshotai_cn_models import get_models
from earendil_works.pi_ai.api.openai_completions import open_ai_completions_api

def moonshotai_cn_provider() -> Provider:
    return create_provider({
        "id": "moonshotai-cn",
        "name": "Moonshot AI CN",
        "auth": {"apiKey": env_api_key_auth("Moonshot AI CN API key", ["MOONSHOT_API_KEY"])},
        "models": get_models(),
        "api": open_ai_completions_api(),
    })

moonshotai_cnProvider = moonshotai_cn_provider
