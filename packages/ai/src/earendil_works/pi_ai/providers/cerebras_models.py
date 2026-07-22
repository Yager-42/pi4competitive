"""Auto catalog for cerebras."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

CEREBRAS_MODELS = load_provider_catalog("cerebras")

def get_models():
    return load_provider_models_list("cerebras")
