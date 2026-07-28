"""SocmStore — atomic read/write of SOCM search_state.json.

research-workflow-v1 v0.2.0 F-R27 / ADR 0010 D-S4. SOCM is the search state of
truth (non-conversation); JSONL remains the conversation SoT (D24). SQLite
projection_json.coverage is a read-only snapshot of this.

Path: ``data/sessions/<session_id>/search_state.json`` — co-located with the
JSONL session so resume reopens both together and DELETE cascades cleanly.

Atomic write: per-store ``asyncio.Lock`` serializes read-modify-write; the
write itself uses tmp + ``os.replace`` so lock-less readers (projection pollers)
never see a half-written file. ``fcntl.flock`` guards cross-process access
(matching SearchOS workspace.py:atomic_update_state).

Adapter/out layer: aiosqlite-free (uses stdlib json + fcntl + os); domain only
imports SOCMState. Not in domain/ because it does filesystem IO (G1).
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Callable

from competitive_app.domain.socm.state import SOCMState


class SocmStore:
    """Atomic SOCM persistence at ``<sessions_root>/<session_id>/search_state.json``."""

    def __init__(self, sessions_root: str | Path) -> None:
        self._root = Path(sessions_root)
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def _lock_for(self, session_id: str) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[session_id] = lock
            return lock

    def _state_path(self, session_id: str) -> Path:
        return self._root / session_id / "search_state.json"

    async def load(self, session_id: str) -> SOCMState:
        """Load SOCM state; return a fresh empty state if none exists yet."""
        path = self._state_path(session_id)
        if not path.is_file():
            return SOCMState()
        data = json.loads(path.read_text(encoding="utf-8"))
        return SOCMState.restore(data)

    async def save(self, session_id: str, state: SOCMState) -> None:
        """Save full state (non-atomic across concurrent writers — prefer atomic_update)."""
        lock = await self._lock_for(session_id)
        async with lock:
            self._write(session_id, state)

    async def atomic_update(
        self,
        session_id: str,
        updater: Callable[[SOCMState], SOCMState],
    ) -> SOCMState:
        """Read-modify-write under per-session lock + fcntl (F-R27/D-S4).

        ``updater`` receives the current state and returns the new state.
        Concurrent same-session flushes serialize on the asyncio.Lock; cross-
        process access serializes on fcntl.flock. The write uses tmp + os.replace
        so readers never see a partial file.
        """
        lock = await self._lock_for(session_id)
        async with lock:
            state = await self._load_unlocked(session_id)
            state = updater(state)
            self._write(session_id, state)
            return state

    async def delete(self, session_id: str) -> None:
        """Delete the SOCM file (called on task DELETE cascade, F-A17 v0.3.0)."""
        lock = await self._lock_for(session_id)
        async with lock:
            path = self._state_path(session_id)
            if path.is_file():
                path.unlink()

    async def exists(self, session_id: str) -> bool:
        return self._state_path(session_id).is_file()

    # ------------------------------------------------------------------ internals

    async def _load_unlocked(self, session_id: str) -> SOCMState:
        path = self._state_path(session_id)
        if not path.is_file():
            return SOCMState()
        data = json.loads(path.read_text(encoding="utf-8"))
        return SOCMState.restore(data)

    def _write(self, session_id: str, state: SOCMState) -> None:
        path = self._state_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(state.snapshot(), ensure_ascii=False, indent=2)
        # Cross-process advisory lock (POSIX; SearchOS workspace.py pattern).
        lock_path = path.parent / ".search_state.json.lock"
        lock_path.touch(exist_ok=True)
        with open(lock_path, "r") as lock_fd:
            try:
                import fcntl

                fcntl.flock(lock_fd, fcntl.LOCK_EX)
            except (ImportError, OSError):
                # Non-POSIX or filesystem without flock — fall back to no cross-
                # process lock (in-process asyncio.Lock still serializes).
                fcntl = None  # type: ignore[assignment]
            try:
                tmp = path.parent / ".search_state.json.tmp"
                tmp.write_text(content, encoding="utf-8")
                os.replace(tmp, path)  # atomic on same filesystem
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)


__all__ = ["SocmStore"]
