"""Session tree and context build.

upstream: packages/agent/src/harness/session/session.ts
"""
from __future__ import annotations

# Contract default (D24/D25): sessions SoT under data/sessions/, not OS temp alone.
DEFAULT_SESSIONS_DIR_NAME = "data/sessions"

__all__ = ["DEFAULT_SESSIONS_DIR_NAME"]
