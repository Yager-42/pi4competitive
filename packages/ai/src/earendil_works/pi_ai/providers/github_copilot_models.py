"""Auto catalog for github-copilot."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

GITHUB_COPILOT_MODELS = load_provider_catalog("github-copilot")

def get_models():
    return load_provider_models_list("github-copilot")
