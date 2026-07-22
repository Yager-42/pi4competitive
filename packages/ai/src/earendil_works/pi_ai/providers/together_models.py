"""Auto catalog for together."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

TOGETHER_MODELS = load_provider_catalog("together")

def get_models():
    return load_provider_models_list("together")
