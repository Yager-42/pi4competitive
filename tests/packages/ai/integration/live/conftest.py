from __future__ import annotations

import pytest

from tests.live_env import live_credentials, live_models_and_model


@pytest.fixture
def live_gateway():
    if not live_credentials():
        pytest.skip("no OPENAI_API_KEY / MODEL_API_KEY in env or .env")
    models, model, creds = live_models_and_model()
    return {
        "models": models,
        "model": model,
        "api_key": creds["api_key"],
        "base_url": creds["base_url"],
        "model_id": creds["model_id"],
    }
