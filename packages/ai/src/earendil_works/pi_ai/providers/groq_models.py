"""Auto catalog for groq."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

GROQ_MODELS = load_provider_catalog("groq")

def get_models():
    return load_provider_models_list("groq")
