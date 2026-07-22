"""Auto catalog for openai-codex."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

OPENAI_CODEX_MODELS = load_provider_catalog("openai-codex")

def get_models():
    return load_provider_models_list("openai-codex")
