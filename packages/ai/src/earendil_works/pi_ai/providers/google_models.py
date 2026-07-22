"""Auto catalog for google."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

GOOGLE_MODELS = load_provider_catalog("google")

def get_models():
    return load_provider_models_list("google")
