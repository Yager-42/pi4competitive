"""Model catalog helpers — port of model-catalog.ts."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

from .types import Model


def flatten_model_catalog(provider: str, groups: dict[str, Any]) -> dict[str, Model]:
    """Flatten API-grouped or already-flat catalogs into id→Model."""
    out: dict[str, Model] = {}
    # Detect flat: values look like models
    sample = next(iter(groups.values()), None) if groups else None
    if isinstance(sample, dict) and "id" in sample and "api" in sample:
        for mid, model in groups.items():
            m = dict(model)
            m.setdefault("id", mid)
            m.setdefault("provider", provider)
            out[str(m["id"])] = m  # type: ignore[assignment]
        return out
    # Grouped by API
    for api, models in groups.items():
        if not isinstance(models, dict):
            continue
        for mid, model in models.items():
            m = dict(model)
            m.setdefault("id", mid)
            m.setdefault("api", api)
            m.setdefault("provider", provider)
            out[str(m["id"])] = m  # type: ignore[assignment]
    return out


def load_provider_catalog(provider: str) -> dict[str, Model]:
    """Load packages/ai providers/data/{provider}.json."""
    data = _read_json(provider)
    return flatten_model_catalog(provider, data)


def load_provider_models_list(provider: str) -> list[Model]:
    return list(load_provider_catalog(provider).values())


def _read_json(provider: str) -> dict[str, Any]:
    # Prefer package resources. Only resource-availability errors should
    # trigger the filesystem fallback; malformed JSON and programming errors
    # must remain visible to callers.
    try:
        pkg = resources.files("earendil_works.pi_ai.providers")
        path = pkg.joinpath("data", f"{provider}.json")
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (ImportError, ModuleNotFoundError, FileNotFoundError, OSError):
        pass
    fs = Path(__file__).resolve().parent / "providers" / "data" / f"{provider}.json"
    if fs.exists():
        return json.loads(fs.read_text(encoding="utf-8"))
    return {}
