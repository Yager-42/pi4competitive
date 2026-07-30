"""SQLite projection store — tasks table + sessions index table.

Contract §7 / feature F-A4/F-A5/F-A22/F-A24. This is the App SQLite projection
at ``data/app.db`` — NOT conversation history (that's JSONL via pi_agent).

Two tables (feature §5.2):
  - tasks: task projection (status/progress/usage) + metadata_json (caller metadata)
  - sessions: session_id → (file_path, cwd, model, system_prompt) index for resume

Single connection + asyncio.Lock serializes writes (feature F-A24); reads are
lock-free (aiosqlite connection is safe for interleaved read cursors, but every
write transaction completes begin→execute→commit inside the lock).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import aiosqlite

_SCHEMA = """
create table if not exists tasks (
    task_id          text primary key,
    session_id       text,
    query            text not null,
    status           text not null,
    created_at       text not null,
    updated_at       text not null,
    metadata_json    text not null,
    projection_json  text not null
);
create index if not exists idx_tasks_status on tasks(status, created_at);

create table if not exists sessions (
    session_id       text primary key,
    file_path        text not null,
    cwd              text not null,
    model            text not null,
    system_prompt    text not null,
    created_at       text not null
);
"""


class TaskProjectionStore:
    """Async SQLite store for task projections + session index."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._db: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()

    async def init(self) -> None:
        if self._db is not None:
            return
        async with self._init_lock:
            if self._db is not None:
                return
            db = await aiosqlite.connect(self._database_url)
            await db.executescript(_SCHEMA)
            await db.commit()
            self._db = db

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------------ tasks

    async def create_task(
        self,
        *,
        task_id: str,
        query: str,
        status: str,
        metadata: dict[str, Any],
        projection: dict[str, Any],
        session_id: str | None = None,
    ) -> None:
        await self.init()
        assert self._db is not None
        now = _now_iso()
        async with self._write_lock:
            await self._db.execute(
                "insert into tasks(task_id, session_id, query, status, created_at, "
                "updated_at, metadata_json, projection_json) values(?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    session_id,
                    query,
                    status,
                    now,  # v0.3.1 fix: real timestamp (was "" via projection.get)
                    now,
                    json.dumps(metadata, ensure_ascii=False),
                    json.dumps(projection, ensure_ascii=False),
                ),
            )
            await self._db.commit()

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        await self.init()
        assert self._db is not None
        async with self._db.execute(
            "select task_id, session_id, query, status, created_at, updated_at, "
            "metadata_json, projection_json from tasks where task_id = ?",
            (task_id,),
        ) as cur:
            row = await cur.fetchone()
        return None if row is None else _row_to_task(row)

    async def list_tasks(self) -> list[dict[str, Any]]:
        await self.init()
        assert self._db is not None
        async with self._db.execute(
            "select task_id, session_id, query, status, created_at, updated_at, "
            "metadata_json, projection_json from tasks order by created_at"
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_task(r) for r in rows]

    async def list_completed_reports(self) -> list[dict[str, Any]]:
        """v0.3.1: completed tasks only, newest first (for GET /reports cards).

        Uses the idx_tasks_status(status, created_at) index. Unfiltered list_tasks()
        is unchanged (GET /tasks still returns all tasks).
        """
        await self.init()
        assert self._db is not None
        async with self._db.execute(
            "select task_id, session_id, query, status, created_at, updated_at, "
            "metadata_json, projection_json from tasks where status = 'completed' "
            "order by created_at desc"
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_task(r) for r in rows]

    async def update_task_status(
        self,
        task_id: str,
        status: str,
        *,
        projection: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> bool:
        """Returns True if a row was updated."""
        await self.init()
        assert self._db is not None
        async with self._write_lock:
            sets = ["status = ?", "updated_at = ?"]
            params: list[Any] = [status, _now_iso()]
            if projection is not None:
                sets.append("projection_json = ?")
                params.append(json.dumps(projection, ensure_ascii=False))
            if session_id is not None:
                sets.append("session_id = ?")
                params.append(session_id)
            params.append(task_id)
            cur = await self._db.execute(
                f"update tasks set {', '.join(sets)} where task_id = ?", params
            )
            await self._db.commit()
            return cur.rowcount > 0

    async def delete_task(self, task_id: str) -> str | None:
        """Delete a task; return its session_id if it had one (for cascade delete)."""
        await self.init()
        assert self._db is not None
        async with self._write_lock:
            async with self._db.execute(
                "select session_id from tasks where task_id = ?", (task_id,)
            ) as cur:
                row = await cur.fetchone()
            session_id = row[0] if row else None
            await self._db.execute("delete from tasks where task_id = ?", (task_id,))
            await self._db.commit()
            return session_id

    # ---------------------------------------------------------------- sessions

    async def index_session(
        self,
        *,
        session_id: str,
        file_path: str,
        cwd: str,
        model: str,
        system_prompt: str,
    ) -> None:
        await self.init()
        assert self._db is not None
        async with self._write_lock:
            await self._db.execute(
                "insert into sessions(session_id, file_path, cwd, model, system_prompt, "
                "created_at) values(?,?,?,?,?,?) on conflict(session_id) do update set "
                "file_path = excluded.file_path, cwd = excluded.cwd, model = excluded.model, "
                "system_prompt = excluded.system_prompt",
                (session_id, file_path, cwd, model, system_prompt, _now_iso()),
            )
            await self._db.commit()

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        await self.init()
        assert self._db is not None
        async with self._db.execute(
            "select session_id, file_path, cwd, model, system_prompt, created_at "
            "from sessions where session_id = ?",
            (session_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return {
            "session_id": row[0],
            "file_path": row[1],
            "cwd": row[2],
            "model": row[3],
            "system_prompt": row[4],
            "created_at": row[5],
        }

    async def delete_session(self, session_id: str) -> None:
        await self.init()
        assert self._db is not None
        async with self._write_lock:
            await self._db.execute("delete from sessions where session_id = ?", (session_id,))
            await self._db.commit()


def _row_to_task(row: Any) -> dict[str, Any]:
    return {
        "task_id": row[0],
        "session_id": row[1],
        "query": row[2],
        "status": row[3],
        "created_at": row[4],
        "updated_at": row[5],
        "metadata": json.loads(row[6]),
        "projection": json.loads(row[7]),
    }


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


__all__ = ["TaskProjectionStore"]
