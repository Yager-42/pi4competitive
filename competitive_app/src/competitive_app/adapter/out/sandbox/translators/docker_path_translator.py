"""Poirot Docker path translator.

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/sandbox/translators/docker_path_translator.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see deploy/tool-sandbox/licenses/POIROT-MIT.txt)
Host delta: import/package path only; fixed workspace mapping retained (COPY).
"""
from __future__ import annotations

from pathlib import Path

_VIRTUAL_PREFIX = "/mnt/poirot/user-data"


class DockerPathTranslator:
    """Translate the fixed container prefix and reverse-map workspace paths."""

    def __init__(self, sandbox_root: str | Path, sandbox_id: str) -> None:
        self._host_root = str(Path(sandbox_root) / sandbox_id).replace("\\", "/")

    def translate_path(self, virtual_path: str) -> str:
        return virtual_path

    def translate_command(self, command: str) -> str:
        return command

    def mask_output(self, output: str) -> str:
        return output

    def reverse_translate(self, virtual_path: str) -> str:
        if virtual_path != _VIRTUAL_PREFIX and not virtual_path.startswith(_VIRTUAL_PREFIX + "/"):
            raise ValueError(f"path not under {_VIRTUAL_PREFIX}: {virtual_path}")
        relative = virtual_path[len(_VIRTUAL_PREFIX):].lstrip("/")
        return f"{self._host_root}/{relative}" if relative else self._host_root


__all__ = ["DockerPathTranslator"]
