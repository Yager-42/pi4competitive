"""Auto catalog for xai."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

XAI_MODELS = load_provider_catalog("xai")

def get_models():
    return load_provider_models_list("xai")
