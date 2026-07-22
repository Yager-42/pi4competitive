"""Auto catalog for cloudflare-ai-gateway."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

CLOUDFLARE_AI_GATEWAY_MODELS = load_provider_catalog("cloudflare-ai-gateway")

def get_models():
    return load_provider_models_list("cloudflare-ai-gateway")
