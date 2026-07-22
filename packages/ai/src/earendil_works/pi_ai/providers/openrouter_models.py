"""Auto catalog for openrouter."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

OPENROUTER_MODELS = load_provider_catalog("openrouter")

def get_models():
    return load_provider_models_list("openrouter")
