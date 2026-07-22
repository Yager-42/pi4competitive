"""Auto catalog for qwen-token-plan-cn."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

QWEN_TOKEN_PLAN_CN_MODELS = load_provider_catalog("qwen-token-plan-cn")

def get_models():
    return load_provider_models_list("qwen-token-plan-cn")
