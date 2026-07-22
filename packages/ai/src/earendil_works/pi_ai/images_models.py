"""Images models collection — structural port of images-models.ts."""
from __future__ import annotations
from typing import Any
from .models import create_models, create_provider
from .types import ImagesModel

class ImagesModels:
    def __init__(self, options: dict[str, Any] | None = None) -> None:
        self._providers: dict[str, Any] = {}

    def set_provider(self, provider: Any) -> None:
        self._providers[provider.id] = provider

    def get_models(self, provider: str | None = None) -> list[ImagesModel]:
        if provider:
            p = self._providers.get(provider)
            return list(p.getModels()) if p else []
        out: list[ImagesModel] = []
        for p in self._providers.values():
            out.extend(p.getModels())
        return out  # type: ignore[return-value]

def create_images_models(options: dict[str, Any] | None = None) -> ImagesModels:
    return ImagesModels(options)
