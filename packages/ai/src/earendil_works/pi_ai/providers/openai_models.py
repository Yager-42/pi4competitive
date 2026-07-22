"""Auto catalog for openai."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

OPENAI_MODELS = load_provider_catalog("openai")

def get_models():
    return load_provider_models_list("openai")
