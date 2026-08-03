"""O7 — circuit breaker: consecutive and rolling denial thresholds.

Source: pi-auto-review@0.3.2 ``broker.test.ts`` (breaker cases)
"""
from __future__ import annotations

from pi_auto_review.circuit_breaker import DenialCircuitBreaker


def test_records_consecutive_denials() -> None:
    breaker = DenialCircuitBreaker(consecutive_limit=3)
    assert breaker.record("scope", True) == {
        "tripped": False,
        "consecutiveDenials": 1,
        "rollingDenials": 1,
    }
    assert breaker.record("scope", True)["consecutiveDenials"] == 2
    result = breaker.record("scope", True)
    assert result["tripped"] is True
    assert result["consecutiveDenials"] == 3


def test_allow_resets_consecutive_denials() -> None:
    breaker = DenialCircuitBreaker(consecutive_limit=3)
    breaker.record("scope", True)
    breaker.record("scope", True)
    breaker.record("scope", False)
    assert breaker.is_tripped("scope") is False
    result = breaker.record("scope", True)
    assert result["consecutiveDenials"] == 1
    assert result["tripped"] is False


def test_rolling_denial_limit_trips() -> None:
    breaker = DenialCircuitBreaker(consecutive_limit=5, rolling_denial_limit=4, rolling_window=10)
    for _ in range(4):
        breaker.record("scope", True)
    assert breaker.is_tripped("scope") is True


def test_rolling_window_evicts_old_denials() -> None:
    breaker = DenialCircuitBreaker(rolling_window=3, rolling_denial_limit=3, consecutive_limit=99)
    for _ in range(3):
        breaker.record("scope", True)
    breaker.record("scope", False)
    assert breaker.is_tripped("scope") is False  # only 2 denials remain in window


def test_scopes_are_isolated() -> None:
    breaker = DenialCircuitBreaker(consecutive_limit=2)
    breaker.record("scope-a", True)
    breaker.record("scope-a", True)
    assert breaker.is_tripped("scope-a") is True
    assert breaker.is_tripped("scope-b") is False
    assert breaker.record("scope-b", True)["tripped"] is False


def test_clear_resets_all_scopes() -> None:
    breaker = DenialCircuitBreaker(consecutive_limit=2)
    breaker.record("scope-a", True)
    breaker.record("scope-a", True)
    assert breaker.is_tripped("scope-a") is True
    breaker.clear()
    assert breaker.is_tripped("scope-a") is False


def test_unknown_scope_not_tripped() -> None:
    assert DenialCircuitBreaker().is_tripped("missing") is False
