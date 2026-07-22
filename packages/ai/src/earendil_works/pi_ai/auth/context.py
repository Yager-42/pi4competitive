"""Default AuthContext — process env."""

from __future__ import annotations

import os

from ..types import ProviderEnv


class DefaultAuthContext:
    def __init__(self, overlay: ProviderEnv | None = None) -> None:
        self._overlay = overlay or {}

    async def env(self, name: str) -> str | None:
        if name in self._overlay and self._overlay[name]:
            return self._overlay[name]
        return os.environ.get(name) or None


def default_auth_context(overlay: ProviderEnv | None = None) -> DefaultAuthContext:
    return DefaultAuthContext(overlay)
