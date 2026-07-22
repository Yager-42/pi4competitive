"""Auto catalog for fireworks."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

FIREWORKS_MODELS = load_provider_catalog("fireworks")

def get_models():
    return load_provider_models_list("fireworks")
