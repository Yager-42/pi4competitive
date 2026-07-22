"""Legacy compat surface — port of compat/."""
from __future__ import annotations
from ..models import create_models, create_provider
from ..providers.all import builtin_models
from ..providers.faux import faux_provider

# Global-style helpers for legacy callers
def get_models():
    return builtin_models()

__all__ = ["create_models", "create_provider", "builtin_models", "faux_provider", "get_models"]
