"""Auto catalog for zai."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

ZAI_MODELS = load_provider_catalog("zai")

def get_models():
    return load_provider_models_list("zai")
