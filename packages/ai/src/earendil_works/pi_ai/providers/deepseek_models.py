"""Auto catalog for deepseek."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

DEEPSEEK_MODELS = load_provider_catalog("deepseek")

def get_models():
    return load_provider_models_list("deepseek")
