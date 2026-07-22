"""Auto catalog for amazon-bedrock."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

AMAZON_BEDROCK_MODELS = load_provider_catalog("amazon-bedrock")

def get_models():
    return load_provider_models_list("amazon-bedrock")
