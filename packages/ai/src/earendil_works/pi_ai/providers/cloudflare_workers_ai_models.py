"""Auto catalog for cloudflare-workers-ai."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

CLOUDFLARE_WORKERS_AI_MODELS = load_provider_catalog("cloudflare-workers-ai")

def get_models():
    return load_provider_models_list("cloudflare-workers-ai")
