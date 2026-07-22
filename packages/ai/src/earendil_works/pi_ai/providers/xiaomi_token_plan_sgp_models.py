"""Auto catalog for xiaomi-token-plan-sgp."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

XIAOMI_TOKEN_PLAN_SGP_MODELS = load_provider_catalog("xiaomi-token-plan-sgp")

def get_models():
    return load_provider_models_list("xiaomi-token-plan-sgp")
