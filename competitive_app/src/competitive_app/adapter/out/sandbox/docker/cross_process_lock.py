"""Poirot cross-process lock helpers.

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/sandbox/docker/cross_process_lock.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see deploy/tool-sandbox/licenses/POIROT-MIT.txt)
Host delta: import/package path only (COPY).
"""
from __future__ import annotations

from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]
    import msvcrt


def open_lock_file(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    return open(lock_path, "a", encoding="utf-8")


def lock_file_exclusive(lock_file) -> None:
    if fcntl is not None:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        return
    lock_file.seek(0)
    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)


def unlock_file(lock_file) -> None:
    if fcntl is not None:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        return
    lock_file.seek(0)
    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


__all__ = ["lock_file_exclusive", "open_lock_file", "unlock_file"]
