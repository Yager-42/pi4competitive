"""Auto catalog for mistral."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

MISTRAL_MODELS = load_provider_catalog("mistral")

def get_models():
    return load_provider_models_list("mistral")
