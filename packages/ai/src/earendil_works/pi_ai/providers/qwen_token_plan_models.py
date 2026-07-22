"""Auto catalog for qwen-token-plan."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

QWEN_TOKEN_PLAN_MODELS = load_provider_catalog("qwen-token-plan")

def get_models():
    return load_provider_models_list("qwen-token-plan")
