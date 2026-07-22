"""Auto catalog for anthropic."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

ANTHROPIC_MODELS = load_provider_catalog("anthropic")

def get_models():
    return load_provider_models_list("anthropic")
