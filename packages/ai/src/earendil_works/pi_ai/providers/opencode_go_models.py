"""Auto catalog for opencode-go."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

OPENCODE_GO_MODELS = load_provider_catalog("opencode-go")

def get_models():
    return load_provider_models_list("opencode-go")
