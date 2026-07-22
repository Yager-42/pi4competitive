"""Auto catalog for moonshotai."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

MOONSHOTAI_MODELS = load_provider_catalog("moonshotai")

def get_models():
    return load_provider_models_list("moonshotai")
