"""Provider factory for google-vertex — isomorphic to providers/google-vertex.ts."""
from __future__ import annotations

async def _ambient_resolve(_args):
    return {"auth": {}, "source": "ambient"}

from ..auth.helpers import env_api_key_auth
from ..models import Provider, create_provider
from .google_vertex_models import get_models
from earendil_works.pi_ai.api.google_vertex import google_vertex_api

def google_vertex_provider() -> Provider:
    return create_provider({
        "id": "google-vertex",
        "name": "Google Vertex",
        "auth": {"apiKey": {"name": "ambient", "resolve": _ambient_resolve}},
        "models": get_models(),
        "api": google_vertex_api(),
    })

google_vertexProvider = google_vertex_provider
