"""Provider factory for amazon-bedrock — isomorphic to providers/amazon-bedrock.ts."""
from __future__ import annotations

async def _ambient_resolve(_args):
    return {"auth": {}, "source": "ambient"}

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .amazon_bedrock_models import get_models
from earendil_works.pi_ai.api.bedrock_converse_stream import bedrock_converse_stream_api

def amazon_bedrock_provider() -> Provider:
    return create_provider({
        "id": "amazon-bedrock",
        "name": "Amazon Bedrock",
        "auth": {"apiKey": {"name": "ambient", "resolve": _ambient_resolve}},
        "models": get_models(),
        "api": bedrock_converse_stream_api(),
    })

amazon_bedrockProvider = amazon_bedrock_provider
