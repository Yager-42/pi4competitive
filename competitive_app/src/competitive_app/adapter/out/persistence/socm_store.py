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
        """Full-state overwrite (in-process atomic; for RMW use ``atomic_update``).

        Serializes with other same-session writers via the per-session
        asyncio.Lock and acquires the cross-process fcntl lock for the write.
        Not safe for read-then-write sequences — use ``atomic_update``.
        """
        lock = await self._lock_for(session_id)
        async with lock:
            self._write_locked(session_id, state)

    async def atomic_update(
        self,
        session_id: str,
        updater: Callable[[SOCMState], SOCMState],
    ) -> SOCMState:
        """Read-modify-write under per-session lock + fcntl (F-R27/D-S4).

        ``updater`` receives the current state and returns the new state.
        Concurrent same-session flushes serialize on the asyncio.Lock; the
        fcntl lock is held across the **entire** read-modify-write so cross-
        process writers cannot interleave (a stale read clobbering a fresh
        write). The write itself uses tmp + os.replace so lock-less readers
        never see a partial file.
        """
        lock = await self._lock_for(session_id)
        async with lock:
            with self._cross_process_lock(session_id) as acquired:
                state = await self._load_unlocked(session_id)
                state = updater(state)
                self._write_unlocked(session_id, state)
                # acquired is only False on non-POSIX; in-process lock still held.
                _ = acquired
            return state

    async def delete(self, session_id: str) -> None:
        """Delete SOCM state while coordinating with all writers.

        The sidecar lock is deliberately retained: another process may still
        hold an open descriptor for it, and unlinking it would create a new inode
        that bypasses that process's flock.
        """
        lock = await self._lock_for(session_id)
        async with lock:
            with self._cross_process_lock(session_id):
                path = self._state_path(session_id)
                if path.is_file():
                    path.unlink()
                tmp = path.parent / ".search_state.json.tmp"
                if tmp.is_file():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
        # Keep the in-process lock entry. Removing it can let a new caller
        # create a second lock while a waiter still references the old one.

    async def exists(self, session_id: str) -> bool:
        return self._state_path(session_id).is_file()

    # ------------------------------------------------------------------ internals

    async def _load_unlocked(self, session_id: str) -> SOCMState:
        path = self._state_path(session_id)
        if not path.is_file():
            return SOCMState()
        data = json.loads(path.read_text(encoding="utf-8"))
        return SOCMState.restore(data)

    # ------------------------------------------------------------------ internals

    def _cross_process_lock(self, session_id: str):
        """Context manager: fcntl.flock around the lock file for the full RMW.

        Returns (acquired: bool). On non-POSIX or unsupported filesystems,
        yields False (no cross-process lock; in-process asyncio.Lock still
        serializes same-process writers).
        """
        import contextlib

        lock_path = self._state_path(session_id).parent / ".search_state.json.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.touch(exist_ok=True)

        @contextlib.contextmanager
        def _cm():
            fd = open(lock_path, "r")
            acquired = False
            try:
                try:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_EX)
                    acquired = True
                except (ImportError, OSError):
                    acquired = False
                yield acquired
            finally:
                if acquired:
                    try:
                        import fcntl

                        fcntl.flock(fd, fcntl.LOCK_UN)
                    except (ImportError, OSError):
                        pass
                fd.close()

        return _cm()

    def _write_locked(self, session_id: str, state: SOCMState) -> None:
        """Write with the cross-process fcntl lock (for ``save``)."""
        with self._cross_process_lock(session_id):
            self._write_unlocked(session_id, state)

    def _write_unlocked(self, session_id: str, state: SOCMState) -> None:
        """Write tmp + os.replace (caller holds the cross-process lock if needed).

        The tmp+replace makes the file swap atomic for lock-less readers even
        if they read concurrently with this write.
        """
        path = self._state_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(state.snapshot(), ensure_ascii=False, indent=2)
        tmp = path.parent / ".search_state.json.tmp"
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)  # atomic on same filesystem


__all__ = ["SocmStore"]
