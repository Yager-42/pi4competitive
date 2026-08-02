"""Denial circuit breaker — consecutive and rolling denial thresholds.

Source: pi-auto-review@0.3.2 ``src/broker/circuit-breaker.ts``
Repository: erichll/pi-packages @ 10c8eeb8269ee478ff7383c7e6139301aa9665f9
License: MIT (retained under the native sandbox license directory)

Host delta (COPY-semantics): same defaults (3 consecutive / 10 rolling in 50),
same ``record``/``isTripped``/``clear`` semantics; results are plain dicts.
"""
from __future__ import annotations

from typing import TypedDict


class CircuitBreakerResult(TypedDict):
    tripped: bool
    consecutiveDenials: int
    rollingDenials: int


class _ScopeState(TypedDict):
    consecutiveDenials: int
    rolling: list[bool]


class DenialCircuitBreaker:
    """Trip per scope key after repeated denials; allows recovery after an allow."""

    def __init__(
        self,
        consecutive_limit: int = 3,
        rolling_denial_limit: int = 10,
        rolling_window: int = 50,
    ) -> None:
        self._scopes: dict[str, _ScopeState] = {}
        self._consecutive_limit = consecutive_limit
        self._rolling_denial_limit = rolling_denial_limit
        self._rolling_window = rolling_window

    def record(self, scope_key: str, denied: bool) -> CircuitBreakerResult:
        state = self._scopes.get(scope_key)
        if state is None:
            state = _ScopeState(consecutiveDenials=0, rolling=[])
        state["consecutiveDenials"] = (
            state["consecutiveDenials"] + 1 if denied else 0
        )
        rolling = state["rolling"]
        rolling.append(denied)
        if len(rolling) > self._rolling_window:
            rolling.pop(0)
        self._scopes[scope_key] = state
        rolling_denials = sum(1 for value in rolling if value)
        return {
            "tripped": (
                state["consecutiveDenials"] >= self._consecutive_limit
                or rolling_denials >= self._rolling_denial_limit
            ),
            "consecutiveDenials": state["consecutiveDenials"],
            "rollingDenials": rolling_denials,
        }

    def is_tripped(self, scope_key: str) -> bool:
        state = self._scopes.get(scope_key)
        if state is None:
            return False
        return (
            state["consecutiveDenials"] >= self._consecutive_limit
            or sum(1 for value in state["rolling"] if value)
            >= self._rolling_denial_limit
        )

    def clear(self) -> None:
        self._scopes.clear()


__all__ = ["CircuitBreakerResult", "DenialCircuitBreaker"]
