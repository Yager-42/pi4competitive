"""Auto catalog for minimax."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

MINIMAX_MODELS = load_provider_catalog("minimax")

def get_models():
    return load_provider_models_list("minimax")
