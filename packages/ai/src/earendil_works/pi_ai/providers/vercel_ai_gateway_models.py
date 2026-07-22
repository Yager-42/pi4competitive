"""Auto catalog for vercel-ai-gateway."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

VERCEL_AI_GATEWAY_MODELS = load_provider_catalog("vercel-ai-gateway")

def get_models():
    return load_provider_models_list("vercel-ai-gateway")
