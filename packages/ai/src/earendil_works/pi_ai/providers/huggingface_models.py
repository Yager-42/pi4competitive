"""Auto catalog for huggingface."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

HUGGINGFACE_MODELS = load_provider_catalog("huggingface")

def get_models():
    return load_provider_models_list("huggingface")
