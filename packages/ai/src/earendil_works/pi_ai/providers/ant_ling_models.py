"""Auto catalog for ant-ling."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

ANT_LING_MODELS = load_provider_catalog("ant-ling")

def get_models():
    return load_provider_models_list("ant-ling")
