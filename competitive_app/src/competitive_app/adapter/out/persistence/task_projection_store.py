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
import uuid
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

create table if not exists task_spans (
    span_id          text primary key,
    task_id          text not null,
    seq              integer not null,
    kind             text not null,
    stage            text,
    entity           text,
    model            text,
    prompt_tokens    integer default 0,
    completion_tokens integer default 0,
    latency_ms       integer default 0,
    ts               text not null
);
create index if not exists idx_task_spans_task on task_spans(task_id, seq);

create table if not exists report_feedback (
    report_id        text primary key,
    edited_blocks    integer default 0,
    total_blocks     integer default 0,
    data_json        text,
    updated_at       text not null
);
CREATE TABLE IF NOT EXISTS skill_records (
    skill_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    generation INTEGER NOT NULL DEFAULT 0,
    origin TEXT NOT NULL DEFAULT 'IMPORTED',
    created_by TEXT,
    description TEXT NOT NULL DEFAULT '',
    allowed_tools TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1,
    total_selections INTEGER NOT NULL DEFAULT 0,
    total_applied INTEGER NOT NULL DEFAULT 0,
    total_completions INTEGER NOT NULL DEFAULT 0,
    total_fallbacks INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_updated TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_records_name ON skill_records(name);
CREATE INDEX IF NOT EXISTS idx_skill_records_active ON skill_records(is_active);
CREATE TABLE IF NOT EXISTS skill_lineage_parents (
    skill_id TEXT NOT NULL,
    parent_skill_id TEXT NOT NULL,
    PRIMARY KEY(skill_id, parent_skill_id)
);
CREATE TABLE IF NOT EXISTS skill_judgments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    applied INTEGER,
    task_completed INTEGER NOT NULL DEFAULT 0,
    ts TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_skill_judgments_skill ON skill_judgments(skill_id, ts);
CREATE TABLE IF NOT EXISTS skill_evolutions (
    evolution_id TEXT PRIMARY KEY,
    skill_name TEXT NOT NULL,
    evolution_type TEXT NOT NULL,
    trigger TEXT NOT NULL,
    baseline_id TEXT,
    candidate_id TEXT NOT NULL,
    failure_focus TEXT NOT NULL DEFAULT '',
    mutation_diff TEXT NOT NULL DEFAULT '',
    eval_score REAL NOT NULL DEFAULT 0.0,
    gate_decision TEXT NOT NULL,
    created_version_id TEXT,
    timestamp TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_skill_evolutions_name ON skill_evolutions(skill_name, timestamp);
CREATE TABLE IF NOT EXISTS skill_eval_judgments (
    judgment_id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    task_id TEXT,
    skill_applied INTEGER NOT NULL,
    deviation_note TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_quality_scores (
    score_id TEXT PRIMARY KEY,
    task_id TEXT,
    task_completion REAL NOT NULL,
    response_quality REAL NOT NULL,
    efficiency REAL NOT NULL,
    tool_usage REAL NOT NULL,
    overall_score REAL NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skill_eval_runs (
    eval_run_id TEXT PRIMARY KEY,
    eval_layer TEXT NOT NULL,
    skill_ids TEXT NOT NULL,
    candidate_id TEXT,
    baseline_id TEXT,
    result_json TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_skill_metadata (
    skill_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL CHECK(scope IN ('plan','search','extraction','write')),
    package_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skill_task_bindings (
    task_id TEXT NOT NULL,
    scope TEXT NOT NULL CHECK(scope IN ('plan','search','extraction','write')),
    ordinal INTEGER NOT NULL,
    skill_id TEXT NOT NULL,
    bound_at TEXT NOT NULL,
    PRIMARY KEY(task_id, scope, ordinal),
    UNIQUE(task_id, scope, skill_id)
);
CREATE INDEX IF NOT EXISTS idx_skill_task_bindings_task ON skill_task_bindings(task_id, scope);
CREATE TABLE IF NOT EXISTS skill_observations (
    observation_id TEXT PRIMARY KEY,
    task_id TEXT,
    scope TEXT NOT NULL CHECK(scope IN ('plan','search','extraction','write')),
    problem_signature TEXT NOT NULL,
    solution TEXT NOT NULL DEFAULT '',
    transferability TEXT NOT NULL DEFAULT '',
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    consumed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_observations_task ON skill_observations(task_id, consumed);
CREATE TABLE IF NOT EXISTS skill_evidence_refs (
    observation_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    ref TEXT NOT NULL,
    PRIMARY KEY(observation_id, kind, ref)
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

    # ------------------------------------------------------- v0.2.2 trace spans

    async def record_span(self, task_id: str, data: dict[str, Any]) -> None:
        """Append one trace span (called from the emit closure for `span` events)."""
        await self.init()
        assert self._db is not None
        async with self._write_lock:
            # seq = current span count for this task (monotonic per task).
            cur = await self._db.execute(
                "select count(*) from task_spans where task_id = ?", (task_id,)
            )
            row = await cur.fetchone()
            seq = row[0] if row else 0
            await self._db.execute(
                "insert into task_spans(span_id, task_id, seq, kind, stage, entity, model, "
                "prompt_tokens, completion_tokens, latency_ms, ts) values(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"sp_{uuid.uuid4().hex[:12]}", task_id, seq,
                    str(data.get("kind", "")), data.get("stage"), data.get("entity"),
                    data.get("model"),
                    int(data.get("prompt_tokens", 0) or 0),
                    int(data.get("completion_tokens", 0) or 0),
                    int(data.get("latency_ms", 0) or 0),
                    _now_iso(),
                ),
            )
            await self._db.commit()

    async def list_spans(self, task_id: str) -> list[dict[str, Any]]:
        """Return all spans for a task, ordered by seq (call order)."""
        await self.init()
        assert self._db is not None
        async with self._db.execute(
            "select span_id, task_id, seq, kind, stage, entity, model, "
            "prompt_tokens, completion_tokens, latency_ms, ts "
            "from task_spans where task_id = ? order by seq",
            (task_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [
            {
                "span_id": r[0], "task_id": r[1], "seq": r[2], "kind": r[3],
                "stage": r[4], "entity": r[5], "model": r[6],
                "prompt_tokens": r[7], "completion_tokens": r[8],
                "latency_ms": r[9], "ts": r[10],
            }
            for r in rows
        ]

    # --------------------------------------------------- v0.3.2 report feedback

    async def save_feedback(
        self, task_id: str, edited_blocks: int, total_blocks: int, data: dict[str, Any]
    ) -> None:
        """Upsert feedback (edited/total blocks + raw data) for a report."""
        await self.init()
        assert self._db is not None
        async with self._write_lock:
            await self._db.execute(
                "insert into report_feedback(report_id, edited_blocks, total_blocks, "
                "data_json, updated_at) values(?,?,?,?,?) "
                "on conflict(report_id) do update set "
                "edited_blocks=excluded.edited_blocks, total_blocks=excluded.total_blocks, "
                "data_json=excluded.data_json, updated_at=excluded.updated_at",
                (
                    task_id, int(edited_blocks), int(total_blocks),
                    json.dumps(data, ensure_ascii=False) if data else None,
                    _now_iso(),
                ),
            )
            await self._db.commit()

    async def get_feedback(self, task_id: str) -> dict[str, Any] | None:
        await self.init()
        assert self._db is not None
        async with self._db.execute(
            "select report_id, edited_blocks, total_blocks, data_json, updated_at "
            "from report_feedback where report_id = ?",
            (task_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        data = json.loads(row[3]) if row[3] else None
        return {
            "report_id": row[0], "edited_blocks": row[1], "total_blocks": row[2],
            "data": data, "updated_at": row[4],
            "revision_rate": (row[1] / row[2]) if row[2] else 0.0,
        }


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
