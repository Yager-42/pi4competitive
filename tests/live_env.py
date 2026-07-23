"""Shared helpers for @pytest.mark.live tests. Never logs secrets."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from earendil_works.pi_ai.types import Model

ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or (ROOT / ".env")
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key:
            os.environ.setdefault(key, val)


def live_credentials() -> dict[str, str] | None:
    """Return {api_key, base_url, model_id} or None if missing key."""
    load_dotenv()
    api_key = (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("MODEL_API_KEY")
        or ""
    ).strip()
    if not api_key:
        return None
    base_url = (
        os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("MODEL_BASE_URL")
        or "https://api.openai.com/v1"
    ).strip().rstrip("/")
    model_id = (
        os.environ.get("OPENAI_MODEL")
        or os.environ.get("MODEL_NAME")
        or "gpt-4o-mini"
    ).strip()
    return {"api_key": api_key, "base_url": base_url, "model_id": model_id}


def live_openai_model(creds: dict[str, str] | None = None) -> Model:
    """OpenAI-compatible Model dict (gateway IDs may be outside static catalog)."""
    c = creds or live_credentials()
    if not c:
        raise RuntimeError("live credentials missing")
    ctx = int(os.environ.get("MODEL_CONTEXT_WINDOW_TOKENS") or "128000")
    return {
        "id": c["model_id"],
        "name": c["model_id"],
        "api": "openai-completions",
        "provider": "openai",
        "baseUrl": c["base_url"],
        "reasoning": False,
        "input": ["text", "image"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": ctx,
        "maxTokens": min(8192, max(1024, ctx // 8)),
    }


def live_models_and_model() -> tuple[Any, Model, dict[str, str]]:
    """create_models() with openai provider + custom model + creds."""
    from earendil_works.pi_ai import create_models
    from earendil_works.pi_ai.providers.openai import openai_provider

    creds = live_credentials()
    if not creds:
        raise RuntimeError("live credentials missing")
    models = create_models()
    models.setProvider(openai_provider())
    model = live_openai_model(creds)
    return models, model, creds
