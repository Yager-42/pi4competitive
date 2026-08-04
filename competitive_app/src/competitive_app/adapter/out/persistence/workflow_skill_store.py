"""Workflow-specific companion persistence in existing app.db.

NEW-HOST adapter. It intentionally does not add fields to Poirot's original
``skill_records`` table and stores no transcript/SOCM body.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS workflow_skill_metadata(
 skill_id TEXT PRIMARY KEY, scope TEXT NOT NULL CHECK(scope IN ('plan','search','extraction','write')),
 package_path TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skill_task_bindings(
 task_id TEXT NOT NULL, scope TEXT NOT NULL CHECK(scope IN ('plan','search','extraction','write')),
 ordinal INTEGER NOT NULL, skill_id TEXT NOT NULL, bound_at TEXT NOT NULL,
 PRIMARY KEY(task_id,scope,ordinal), UNIQUE(task_id,scope,skill_id)
);
CREATE INDEX IF NOT EXISTS idx_skill_task_bindings_task ON skill_task_bindings(task_id,scope);
CREATE TABLE IF NOT EXISTS skill_observations(
 observation_id TEXT PRIMARY KEY, task_id TEXT, scope TEXT NOT NULL CHECK(scope IN ('plan','search','extraction','write')),
 problem_signature TEXT NOT NULL, solution TEXT NOT NULL DEFAULT '', transferability TEXT NOT NULL DEFAULT '',
 evidence_refs_json TEXT NOT NULL DEFAULT '[]', consumed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_observations_task ON skill_observations(task_id,consumed);
CREATE TABLE IF NOT EXISTS skill_evidence_refs(
 observation_id TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL,
 PRIMARY KEY(observation_id,kind,ref)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowSkillStore:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()

    async def init(self) -> None:
        if self._db is not None:
            return
        async with self._init_lock:
            if self._db is None:
                Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
                db = await aiosqlite.connect(self._db_path)
                db.row_factory = aiosqlite.Row
                await db.executescript(_SCHEMA)
                await db.commit()
                self._db = db

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def _ready(self) -> aiosqlite.Connection:
        await self.init()
        assert self._db is not None
        return self._db

    async def set_scope(self, skill_id: str, scope: str, package_path: str) -> None:
        db = await self._ready()
        now = _now()
        async with self._write_lock:
            await db.execute("""INSERT INTO workflow_skill_metadata(skill_id,scope,package_path,created_at,updated_at)
                VALUES(?,?,?,?,?) ON CONFLICT(skill_id) DO UPDATE SET scope=excluded.scope,package_path=excluded.package_path,updated_at=excluded.updated_at""",
                           (skill_id, scope, package_path, now, now))
            await db.commit()

    async def get_scope(self, skill_id: str) -> str | None:
        db = await self._ready()
        async with db.execute("SELECT scope FROM workflow_skill_metadata WHERE skill_id=?", (skill_id,)) as cur:
            row = await cur.fetchone()
        return row[0] if row else None

    async def list_scoped_skill_ids(self, scope: str) -> list[str]:
        db = await self._ready()
        async with db.execute("SELECT skill_id FROM workflow_skill_metadata WHERE scope=? ORDER BY skill_id", (scope,)) as cur:
            return [row[0] for row in await cur.fetchall()]

    async def bind(self, task_id: str, scope: str, skill_ids: list[str]) -> list[str]:
        """Atomically persist first binding; an existing binding is immutable."""
        if len(skill_ids) > 3:
            raise ValueError("at most three Skills may be bound per scope")
        db = await self._ready()
        normalized = list(dict.fromkeys(skill_ids))
        async with self._write_lock:
            async with db.execute("SELECT skill_id FROM skill_task_bindings WHERE task_id=? AND scope=? ORDER BY ordinal", (task_id, scope)) as cur:
                existing = [row[0] for row in await cur.fetchall()]
            if existing:
                return [skill_id for skill_id in existing if skill_id]
            now = _now()
            rows = normalized or [""]
            for ordinal, skill_id in enumerate(rows):
                await db.execute("INSERT INTO skill_task_bindings(task_id,scope,ordinal,skill_id,bound_at) VALUES(?,?,?,?,?)",
                                 (task_id, scope, ordinal, skill_id, now))
            await db.commit()
        return normalized

    async def has_binding(self, task_id: str, scope: str) -> bool:
        db = await self._ready()
        async with db.execute("SELECT 1 FROM skill_task_bindings WHERE task_id=? AND scope=? LIMIT 1", (task_id, scope)) as cur:
            return await cur.fetchone() is not None

    async def get_bindings(self, task_id: str, scope: str | None = None) -> dict[str, list[str]] | list[str]:
        db = await self._ready()
        if scope is not None:
            async with db.execute("SELECT skill_id FROM skill_task_bindings WHERE task_id=? AND scope=? ORDER BY ordinal", (task_id, scope)) as cur:
                return [row[0] for row in await cur.fetchall() if row[0]]
        async with db.execute("SELECT scope,skill_id FROM skill_task_bindings WHERE task_id=? ORDER BY scope,ordinal", (task_id,)) as cur:
            result: dict[str, list[str]] = {}
            for row in await cur.fetchall():
                if row[1]: result.setdefault(row[0], []).append(row[1])
        return result

    async def delete_task_bindings(self, task_id: str) -> None:
        db = await self._ready()
        async with self._write_lock:
            await db.execute("DELETE FROM skill_task_bindings WHERE task_id=?", (task_id,))
            await db.execute("DELETE FROM skill_evidence_refs WHERE observation_id IN (SELECT observation_id FROM skill_observations WHERE task_id=? AND consumed=0)", (task_id,))
            await db.execute("DELETE FROM skill_observations WHERE task_id=? AND consumed=0", (task_id,))
            await db.commit()

    async def add_observation(
        self,
        *,
        observation_id: str,
        task_id: str | None,
        scope: str,
        problem_signature: str,
        solution: str = "",
        transferability: str = "",
        evidence_refs: list[dict[str, Any]] | None = None,
    ) -> str:
        db = await self._ready()
        async with self._write_lock:
            await db.execute("""INSERT INTO skill_observations
                (observation_id,task_id,scope,problem_signature,solution,transferability,evidence_refs_json,consumed,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (observation_id, task_id, scope, problem_signature, solution, transferability,
                 json.dumps(evidence_refs or [], ensure_ascii=False), 0, _now()))
            for evidence in evidence_refs or []:
                if not isinstance(evidence, dict):
                    continue
                kind = str(evidence.get("kind") or evidence.get("type") or "")
                ref = str(evidence.get("ref") or evidence.get("id") or evidence.get("url") or "")
                if kind and ref:
                    await db.execute(
                        "INSERT OR IGNORE INTO skill_evidence_refs(observation_id,kind,ref) VALUES(?,?,?)",
                        (observation_id, kind, ref),
                    )
            await db.commit()
        return observation_id

    async def list_observations(self, scope: str | None = None, unconsumed_only: bool = True) -> list[dict[str, Any]]:
        db = await self._ready()
        query = "SELECT * FROM skill_observations WHERE 1=1"
        args: list[Any] = []
        if scope is not None:
            query += " AND scope=?"
            args.append(scope)
        if unconsumed_only:
            query += " AND consumed=0"
        query += " ORDER BY created_at"
        async with db.execute(query, args) as cur:
            rows = await cur.fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["evidence_refs"] = json.loads(item.pop("evidence_refs_json") or "[]")
            except json.JSONDecodeError:
                item["evidence_refs"] = []
            result.append(item)
        return result

    async def mark_consumed(self, observation_id: str) -> bool:
        db = await self._ready()
        async with self._write_lock:
            # Compare-and-set makes consumption atomic: exactly one concurrent
            # consumer can claim an unconsumed observation.
            cur = await db.execute(
                "UPDATE skill_observations SET consumed=1 "
                "WHERE observation_id=? AND consumed=0", (observation_id,)
            )
            await db.commit()
        return cur.rowcount > 0


__all__ = ["WorkflowSkillStore"]
