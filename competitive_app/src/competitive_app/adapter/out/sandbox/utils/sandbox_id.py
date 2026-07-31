"""Deterministic full-width P3.3 scope identity.

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/sandbox/utils/sandbox_id.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see deploy/tool-sandbox/licenses/POIROT-MIT.txt)
Host delta: version + local-default tenant + parent session recipe and full
64-hex validation instead of the parent 8-hex prefix (ADAPT).
"""
from __future__ import annotations

import hashlib

from ..types import require_scope_id

SANDBOX_ID_VERSION = "agent-tool-sandbox-v1"
DEFAULT_TENANT_ID = "local-default"


def derive_sandbox_id(parent_session_id: str, *, tenant_id: str = DEFAULT_TENANT_ID) -> str:
    if not isinstance(parent_session_id, str) or not parent_session_id:
        raise ValueError("parent session id must be non-empty")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise ValueError("tenant id must be non-empty")
    value = hashlib.sha256(
        SANDBOX_ID_VERSION.encode("utf-8")
        + b"\0"
        + tenant_id.encode("utf-8")
        + b"\0"
        + parent_session_id.encode("utf-8")
    ).hexdigest()
    return require_scope_id(value)


def validate_sandbox_id(sandbox_id: str) -> None:
    require_scope_id(sandbox_id)


__all__ = ["DEFAULT_TENANT_ID", "SANDBOX_ID_VERSION", "derive_sandbox_id", "validate_sandbox_id"]
