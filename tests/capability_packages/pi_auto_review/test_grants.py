"""O6 — grant store: stable hash, TTL, one-shot use (PORT broker.test.ts grant cases).

Source: pi-auto-review@0.3.2 ``broker.test.ts``
"""
from __future__ import annotations

from pi_auto_review.grants import OneShotGrantStore, boundary_request_hash


def _request(**overrides: object) -> dict[str, object]:
    base = {
        "id": "r1",
        "source": "sandbox-runtime",
        "surface": "network",
        "operation": "connect",
        "cwd": "/tmp/workspace",
        "destination": "api.example.com:443",
    }
    base.update(overrides)
    return base


def test_hash_is_stable_across_field_order() -> None:
    left = boundary_request_hash(
        _request(destination="api.example.com:443", toolName="fetch")
    )
    right = boundary_request_hash(
        _request(toolName="fetch", destination="api.example.com:443")
    )
    assert left == right
    assert len(left) == 64


def test_hash_changes_when_approval_fields_change() -> None:
    base = _request()
    assert boundary_request_hash(base) != boundary_request_hash(
        _request(destination="other.example.com:443")
    )
    assert boundary_request_hash(base) != boundary_request_hash(
        _request(operation="bind")
    )
    assert boundary_request_hash(base) != boundary_request_hash(_request(surface="filesystem-write"))




def test_grant_issue_exact_fields() -> None:
    store = OneShotGrantStore(ttl_ms=60_000)
    grant = store.issue(_request(), "session-a")
    assert grant["requestHash"] == boundary_request_hash(_request())
    assert grant["sessionId"] == "session-a"
    assert grant["usesRemaining"] == 1
    assert grant["token"]
    assert grant["expiresAt"] > 0


def test_grant_consume_single_use() -> None:
    store = OneShotGrantStore()
    request = _request()
    grant = store.issue(request, "session-a")
    assert store.consume(request, "session-a", grant["token"]) is True
    assert store.consume(request, "session-a", grant["token"]) is False


def test_grant_consume_rejects_unknown_token() -> None:
    store = OneShotGrantStore()
    request = _request()
    store.issue(request, "session-a")
    assert store.consume(request, "session-a", "not-a-token") is False


def test_grant_consume_rejects_session_mismatch() -> None:
    store = OneShotGrantStore()
    request = _request()
    grant = store.issue(request, "session-a")
    assert store.consume(request, "session-b", grant["token"]) is False
    # the grant is still valid for the right session
    assert store.consume(request, "session-a", grant["token"]) is True


def test_grant_consume_rejects_request_hash_mismatch() -> None:
    store = OneShotGrantStore()
    grant = store.issue(_request(), "session-a")
    assert store.consume(_request(destination="other.example.com:443"), "session-a", grant["token"]) is False


def test_grant_expires_after_ttl() -> None:
    now = [1_000_000.0]
    store = OneShotGrantStore(ttl_ms=60_000, now=lambda: now[0])
    grant = store.issue(_request(), "session-a")
    now[0] += 60_001
    assert store.consume(_request(), "session-a", grant["token"]) is False


def test_prune_removes_expired() -> None:
    now = [1_000_000.0]
    store = OneShotGrantStore(ttl_ms=60_000, now=lambda: now[0])
    store.issue(_request(), "session-a")
    now[0] += 60_001
    store.prune()
    assert store._grants == {}  # type: ignore[attr-defined]


def test_clear_removes_all_grants() -> None:
    store = OneShotGrantStore()
    request = _request()
    grant = store.issue(request, "session-a")
    store.clear()
    assert store.consume(request, "session-a", grant["token"]) is False


def test_issue_tokens_are_unique() -> None:
    store = OneShotGrantStore()
    tokens = {store.issue(_request(), "session-a")["token"] for _ in range(20)}
    assert len(tokens) == 20
