"""Learned Skill file and active manifest projection (NEW-HOST).

Only ``SKILL.md`` and ``.skill_id`` are generated. Candidate/history files stay
under ``skills/<skill-id>/``; the atomic manifest lists only each name's unique
active path. No crash reconciliation or garbage collector is implemented.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from ...domain.evolution.skill_types import SkillRecord

_log = logging.getLogger(__name__)


def _atomic_write(path: Path, payload: bytes) -> None:
    """Write a projection file via fsync + same-directory replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        # Persist the rename itself; without a directory fsync the entry can
        # still be lost on crash after the file itself was durable.
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass





class SkillFiles:
    def __init__(self, root_dir: str | Path, skill_store: Any, scope_store: Any | None = None) -> None:
        self._root = Path(root_dir)
        self._skills_root = self._root / "skills"
        self._manifest = self._root / "package.json"
        self._store = skill_store
        self._scope_store = scope_store
        self._mu = asyncio.Lock()

    async def accept_candidate(self, candidate: SkillRecord, scope: str | None = None) -> str:
        async with self._mu:
            self._skills_root.mkdir(parents=True, exist_ok=True)
            path = Path(candidate.path)
            if not path.is_file():
                raise FileNotFoundError(path)
            marker = path.parent / ".skill_id"
            previous_marker = marker.read_bytes() if marker.is_file() else None
            scope_attempted = False
            marker_written = False
            previous_scope: str | None = None
            try:
                # Dependent projection state must exist before the manifest can
                # publish this active path.  Manifest replacement is last.
                _atomic_write(marker, candidate.skill_id.encode("utf-8"))
                marker_written = True
                if self._scope_store is not None and scope is not None:
                    scope_attempted = True
                    previous_scope = await self._read_scope_locked(candidate.skill_id)
                    await self._scope_store.set_scope(candidate.skill_id, scope, str(path))
                await self._write_manifest_locked()
            except Exception:
                if scope_attempted:
                    try:
                        if previous_scope is not None:
                            await self._scope_store.set_scope(
                                candidate.skill_id, previous_scope, str(path)
                            )
                        else:
                            await self._clear_scope_locked(candidate.skill_id)
                    except Exception:
                        _log.exception("scope rollback failed for skill %s", candidate.skill_id)
                if marker_written:
                    try:
                        if previous_marker is None:
                            marker.unlink()
                        else:
                            _atomic_write(marker, previous_marker)
                    except Exception:
                        _log.exception("marker rollback failed for skill %s", candidate.skill_id)
                raise
        return str(path)

    async def _read_scope_locked(self, skill_id: str) -> str | None:
        getter = getattr(self._scope_store, "get_scope", None)
        if getter is None:
            return None
        result = getter(skill_id)
        if hasattr(result, "__await__"):
            return await result
        return result

    async def _clear_scope_locked(self, skill_id: str) -> None:
        if self._scope_store is None:
            return
        for name in ("remove_scope", "delete_scope", "clear_scope"):
            clearer = getattr(self._scope_store, name, None)
            if clearer is None:
                continue
            result = clearer(skill_id)
            if hasattr(result, "__await__"):
                await result
            return
        _log.warning(
            "scope store has no remove/delete/clear_scope; scope row for %s "
            "cannot be rolled back",
            skill_id,
        )

    async def reject_candidate(self, candidate: SkillRecord) -> None:
        async with self._mu:
            path = Path(candidate.path)
            for item in (path, path.parent / ".skill_id"):
                try:
                    item.unlink()
                except FileNotFoundError:
                    pass
            try:
                path.parent.rmdir()
            except OSError:
                pass

    async def rollback(self, skill_id: str) -> None:
        await self._store.rollback(skill_id)
        async with self._mu:
            await self._write_manifest_locked()

    async def update_manifest(self) -> None:
        async with self._mu:
            await self._write_manifest_locked()

    async def _write_manifest_locked(self) -> None:
        records = await self._store.list_active()
        active = []
        for record in records:
            path = Path(record.path)
            try:
                relative = path.relative_to(self._root).as_posix()
            except ValueError:
                relative = f"skills/{record.skill_id}/SKILL.md"
            active.append(relative)
        active.sort()
        self._root.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {"name": "learned-skills", "version": "0.1.0", "pi": {"skills": active}}
        fd, temporary = tempfile.mkstemp(prefix="package.", suffix=".json", dir=self._root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._manifest)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


__all__ = ["SkillFiles"]
