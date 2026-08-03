"""Poirot security guard contract.

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/sandbox/contracts/security_guard.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see native/vendor/licenses/POIROT-MIT.txt)
Host delta: import/package path only (COPY).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SecurityGuard(Protocol):
    def validate_path(self, path: str, *, write: bool = False) -> None: ...

    def validate_command(self, command: str) -> None: ...
