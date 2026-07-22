"""Provider factory for google — isomorphic to providers/google.ts."""
from __future__ import annotations

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .google_models import get_models
from earendil_works.pi_ai.api.google_generative_ai import google_generative_ai_api

def google_provider() -> Provider:
    return create_provider({
        "id": "google",
        "name": "Google",
        "baseUrl": "https://generativelanguage.googleapis.com/v1beta",
        "auth": {"apiKey": env_api_key_auth("Google API key", ["GEMINI_API_KEY"])},
        "models": get_models(),
        "api": google_generative_ai_api(),
    })

googleProvider = google_provider
