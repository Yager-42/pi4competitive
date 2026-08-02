"""Poirot path translator contract.

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/sandbox/contracts/path_translator.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see native/vendor/licenses/POIROT-MIT.txt)
Host delta: import/package path only (COPY).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PathTranslator(Protocol):
    def translate_path(self, virtual_path: str) -> str: ...

    def translate_command(self, command: str) -> str: ...

    def mask_output(self, output: str) -> str: ...
