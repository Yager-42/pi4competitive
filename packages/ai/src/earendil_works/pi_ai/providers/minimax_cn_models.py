"""Auto catalog for minimax-cn."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

MINIMAX_CN_MODELS = load_provider_catalog("minimax-cn")

def get_models():
    return load_provider_models_list("minimax-cn")
