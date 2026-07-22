"""Auto catalog for kimi-coding."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

KIMI_CODING_MODELS = load_provider_catalog("kimi-coding")

def get_models():
    return load_provider_models_list("kimi-coding")
