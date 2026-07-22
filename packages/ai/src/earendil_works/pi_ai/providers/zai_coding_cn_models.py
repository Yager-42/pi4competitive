"""Auto catalog for zai-coding-cn."""
from __future__ import annotations
from ..model_catalog import load_provider_catalog, load_provider_models_list

ZAI_CODING_CN_MODELS = load_provider_catalog("zai-coding-cn")

def get_models():
    return load_provider_models_list("zai-coding-cn")
