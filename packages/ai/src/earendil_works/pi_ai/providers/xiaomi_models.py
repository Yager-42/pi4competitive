"""Auto catalog for xiaomi."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

XIAOMI_MODELS = load_provider_catalog("xiaomi")

def get_models():
    return load_provider_models_list("xiaomi")
