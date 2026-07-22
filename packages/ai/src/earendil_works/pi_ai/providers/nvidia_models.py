"""Auto catalog for nvidia."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

NVIDIA_MODELS = load_provider_catalog("nvidia")

def get_models():
    return load_provider_models_list("nvidia")
