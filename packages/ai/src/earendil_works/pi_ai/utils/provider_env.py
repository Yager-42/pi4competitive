"""Provider-scoped environment resolution."""

from __future__ import annotations

import os

from ..types import ProviderEnv


def resolve_env_value(name: str, env: ProviderEnv | None = None) -> str | None:
    if env and name in env and env[name]:
        return env[name]
    return os.environ.get(name) or None
