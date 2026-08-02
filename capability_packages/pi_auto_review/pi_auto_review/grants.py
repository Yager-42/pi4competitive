"""One-shot grant store and stable boundary request hash.

Source: pi-auto-review@0.3.2 ``src/broker/grants.ts``
Repository: erichll/pi-packages @ 10c8eeb8269ee478ff7383c7e6139301aa9665f9
License: MIT (retained under the native sandbox license directory)

Host delta (COPY-semantics): TypeScript ``createHash/randomUUID`` become
``hashlib/uuid``; ``JSON.stringify`` is reproduced byte-identically with compact
separators; key sort order matches ``localeCompare`` for the ASCII field names
used here. ``Date.now`` becomes an injectable ``now() -> epoch ms`` callable.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from typing import Any

from earendil_works.pi_agent.boundary_approval import BoundaryGrant, BoundaryRequest

_HASH_FIELDS = (
    "source",
    "surface",
    "operation",
    "cwd",
    "command",
    "path",
    "resolvedPath",
    "destination",
    "toolCallId",
    "toolName",
    "skillName",
    "toolInputPreview",
    "agentName",
    "matchedPolicy",
)


def _stable_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_stable_value(item) for item in value]
    if value is None or not isinstance(value, dict):
        return value
    return {
        key: _stable_value(child)
        for key, child in sorted(value.items())
        if child is not None
    }


def boundary_request_hash(request: BoundaryRequest) -> str:
    """Stable canonical SHA-256 of the request's approval-relevant fields."""
    material = {name: request.get(name) for name in _HASH_FIELDS}
    payload = json.dumps(_stable_value(material), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class OneShotGrantStore:
    """Exact single-use grants with TTL; a consumed or expired grant never re-issues."""

    def __init__(
        self,
        ttl_ms: int = 60_000,
        now: Callable[[], float] | None = None,
    ) -> None:
        import time

        self._ttl_ms = ttl_ms
        self._now = now or (lambda: time.time() * 1000)
        self._grants: dict[str, dict[str, Any]] = {}

    def issue(self, request: BoundaryRequest, session_id: str) -> BoundaryGrant:
        self.prune()
        grant: BoundaryGrant = {
            "token": str(uuid.uuid4()),
            "requestHash": boundary_request_hash(request),
            "sessionId": session_id,
            "expiresAt": int(self._now() + self._ttl_ms),
            "usesRemaining": 1,
        }
        self._grants[grant["token"]] = dict(grant)
        return grant

    def consume(self, request: BoundaryRequest, session_id: str, token: str) -> bool:
        self.prune()
        grant = self._grants.get(token)
        if (
            grant is None
            or grant["sessionId"] != session_id
            or grant["requestHash"] != boundary_request_hash(request)
            or grant["usesRemaining"] != 1
        ):
            return False
        del self._grants[token]
        return True

    def clear(self) -> None:
        self._grants.clear()

    def prune(self) -> None:
        now = self._now()
        expired = [
            token
            for token, grant in self._grants.items()
            if grant["expiresAt"] <= now or grant["usesRemaining"] < 1
        ]
        for token in expired:
            del self._grants[token]


__all__ = ["OneShotGrantStore", "boundary_request_hash"]
