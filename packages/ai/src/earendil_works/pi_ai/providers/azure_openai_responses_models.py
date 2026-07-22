"""Auto catalog for azure-openai-responses."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

AZURE_OPENAI_RESPONSES_MODELS = load_provider_catalog("azure-openai-responses")

def get_models():
    return load_provider_models_list("azure-openai-responses")
