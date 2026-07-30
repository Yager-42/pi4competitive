"""Learned Skill file and active manifest projection (NEW-HOST).

Only ``SKILL.md`` and ``.skill_id`` are generated. Candidate/history files stay
under ``skills/<skill-id>/``; the atomic manifest lists only each name's unique
active path. No crash reconciliation or garbage collector is implemented.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ...domain.evolution.skill_types import SkillRecord


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
            (path.parent / ".skill_id").write_text(candidate.skill_id, encoding="utf-8")
            if self._scope_store is not None and scope is not None:
                await self._scope_store.set_scope(candidate.skill_id, scope, str(path))
            await self._write_manifest_locked()
        return str(path)

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
