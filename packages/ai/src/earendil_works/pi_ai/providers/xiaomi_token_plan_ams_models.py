"""Auto catalog for xiaomi-token-plan-ams."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

XIAOMI_TOKEN_PLAN_AMS_MODELS = load_provider_catalog("xiaomi-token-plan-ams")

def get_models():
    return load_provider_models_list("xiaomi-token-plan-ams")
