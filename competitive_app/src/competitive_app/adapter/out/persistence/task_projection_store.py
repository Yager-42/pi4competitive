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
from datetime import UTC
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

-- v0.3.3 全局证据溯源库:任务完成时从 SOCM evidence_graph 扁平化入库,
-- 释放 pi4 evidence 结构化优势(entity/attribute 可检索);SQLite 是投影,
-- SOCM JSON 仍是搜索 SoT(D-S4)。先删后插保证 resume 一致。
create table if not exists evidences (
    evidence_id      text primary key,
    task_id          text not null,
    entity           text,
    attribute        text,
    value            text,
    finding          text,
    source_url       text,
    source_type      text,
    domain           text,
    brand            text,
    confidence       real default 0,
    captured_at      text
);
create index if not exists idx_evidences_brand on evidences(brand);
create index if not exists idx_evidences_type on evidences(source_type);
create index if not exists idx_evidences_task on evidences(task_id);

-- v0.3.3 订阅监控:保存的查询 + 手动重跑 + 运行历史(对齐 VerdaAI,无定时器)。
create table if not exists subscriptions (
    sub_id           text primary key,
    query            text not null,
    brands_json      text,
    interval_hours   integer default 24,
    created_at       text not null,
    last_run_at      text,
    last_task_id     text,
    run_count        integer default 0
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

    async def update_task_metadata(self, task_id: str, metadata: dict[str, Any]) -> None:
        """v0.3.3: update a task's metadata_json (clarify answers/brief, etc.)."""
        await self.init()
        assert self._db is not None
        async with self._write_lock:
            await self._db.execute(
                "update tasks set metadata_json = ?, updated_at = ? where task_id = ?",
                (json.dumps(metadata, ensure_ascii=False), _now_iso(), task_id),
            )
            await self._db.commit()

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
            # v0.3.3: cascade delete this task's projected evidences (same txn).
            await self._db.execute("delete from evidences where task_id = ?", (task_id,))
            # v0.3.2: cascade delete this task's trace spans + feedback too.
            await self._db.execute("delete from task_spans where task_id = ?", (task_id,))
            await self._db.execute("delete from report_feedback where report_id = ?", (task_id,))
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
                    f"sp_{uuid.uuid4().hex[:12]}",
                    task_id,
                    seq,
                    str(data.get("kind", "")),
                    data.get("stage"),
                    data.get("entity"),
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
                "span_id": r[0],
                "task_id": r[1],
                "seq": r[2],
                "kind": r[3],
                "stage": r[4],
                "entity": r[5],
                "model": r[6],
                "prompt_tokens": r[7],
                "completion_tokens": r[8],
                "latency_ms": r[9],
                "ts": r[10],
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
                    task_id,
                    int(edited_blocks),
                    int(total_blocks),
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
            "report_id": row[0],
            "edited_blocks": row[1],
            "total_blocks": row[2],
            "data": data,
            "updated_at": row[4],
            "revision_rate": (row[1] / row[2]) if row[2] else 0.0,
        }

    # ----------------------------------------------- v0.3.3 global evidence lib

    async def index_evidences(self, task_id: str, nodes: list[Any], task_created_at: str) -> None:
        """Flatten a task's SOCM evidence nodes into the global evidences table.

        v0.3.3: called from the runner completion hook. SQLite is a projection —
        SOCM JSON remains the search SoT (D-S4). Delete-then-insert per task so a
        resume re-run (fewer/different nodes) stays consistent. Only ACTIVE nodes
        are indexed; rejected/superseded are dropped.
        """
        await self.init()
        assert self._db is not None
        rows: list[tuple[Any, ...]] = []
        for n in nodes:
            status = _node_status(n)
            if status != "active":
                continue
            source = _node_source(n)
            source_type, domain = _classify_source(source)
            rows.append(
                (
                    f"{task_id}:{str(_node_id(n)).strip() or f'ev_{uuid.uuid4().hex}'}",
                    task_id,
                    _node_field(n, "entity"),
                    _node_field(n, "attribute"),
                    _node_field(n, "value"),
                    _node_field(n, "finding"),
                    source,
                    source_type,
                    domain,
                    _node_field(n, "entity"),  # brand == entity (competitor name)
                    float(_node_field(n, "confidence") or 0),
                    task_created_at or _now_iso(),
                )
            )
        async with self._write_lock:
            await self._db.execute("delete from evidences where task_id = ?", (task_id,))
            if rows:
                await self._db.executemany(
                    "insert or replace into evidences(evidence_id, task_id, entity, attribute, "
                    "value, finding, source_url, source_type, domain, brand, confidence, "
                    "captured_at) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                    rows,
                )
            await self._db.commit()

    async def query_evidences(
        self,
        *,
        brand: str | None = None,
        brands: list[str] | None = None,
        source_type: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Query the global evidence lib with optional filters (v0.3.3).

        v0.2.5 (memory inject): ``brands`` (list) does a case-insensitive
        multi-brand match (``lower(brand) IN (...)``) for recall by competitor.
        ``brand`` (single, exact) is kept for the /evidences route (backward-compat).
        """
        await self.init()
        assert self._db is not None
        sql = (
            "select evidence_id, task_id, entity, attribute, value, finding, "
            "source_url, source_type, domain, brand, confidence, captured_at "
            "from evidences where confidence >= ?"
        )
        params: list[Any] = [min_confidence]
        if brand:
            sql += " and brand = ?"
            params.append(brand)
        if brands:
            placeholders = ",".join("lower(?)" for _ in brands)
            sql += f" and lower(brand) in ({placeholders})"
            params.extend(brands)
        if source_type:
            sql += " and source_type = ?"
            params.append(source_type)
        sql += " order by confidence desc, captured_at desc limit ?"
        params.append(limit)
        async with self._db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [
            {
                "evidence_id": r[0],
                "task_id": r[1],
                "entity": r[2],
                "attribute": r[3],
                "value": r[4],
                "finding": r[5],
                "source_url": r[6],
                "source_type": r[7],
                "domain": r[8],
                "brand": r[9],
                "confidence": r[10],
                "captured_at": r[11],
            }
            for r in rows
        ]

    async def evidence_facets(self) -> dict[str, Any]:
        """Aggregation facets for the evidence lib: total / by_type / by_brand."""
        await self.init()
        assert self._db is not None
        async with self._db.execute("select count(*) n from evidences") as cur:
            total = (await cur.fetchone())[0]
        async with self._db.execute(
            "select source_type, count(*) n from evidences group by source_type"
        ) as cur:
            by_type = {r[0]: r[1] for r in await cur.fetchall()}
        async with self._db.execute(
            "select brand, count(*) n from evidences where brand != '' "
            "group by brand order by n desc limit 12"
        ) as cur:
            by_brand = {r[0]: r[1] for r in await cur.fetchall()}
        return {"total": total, "by_type": by_type, "by_brand": by_brand}

    # ----------------------------------------------------- v0.3.3 dashboard

    async def dashboard_stats(self) -> dict[str, Any]:
        """Pure-SQL global aggregation over tasks/evidences/task_spans (v0.3.3).

        No SOCM JSON reads — fast. Returns 0s on empty DB (divide-by-zero guarded).
        """
        await self.init()
        assert self._db is not None

        async def _scalar(sql: str, params: tuple = ()) -> Any:
            async with self._db.execute(sql, params) as cur:  # type: ignore[union-attr]
                row = await cur.fetchone()
            return row[0] if row else 0

        reports = await _scalar("select count(*) from tasks where status = 'completed'")
        tasks_total = await _scalar("select count(*) from tasks")
        evidence_total = await _scalar("select count(*) from evidences")
        high_conf_total = await _scalar("select count(*) from evidences where confidence >= 0.7")
        claim_total = await _scalar(
            "select coalesce(sum(cast(json_extract(projection_json, "
            "'$.claim_count') as integer)),0) from tasks where status = 'completed'"
        )
        token_total = await _scalar(
            "select coalesce(sum(prompt_tokens + completion_tokens),0) from task_spans"
        )
        avg_coverage = await _scalar(
            "select coalesce(avg(cast(json_extract(projection_json, "
            "'$.coverage.ratio') as real)),0) from tasks where status = 'completed'"
        )
        # tasks_by_status
        async with self._db.execute(  # type: ignore[union-attr]
            "select status, count(*) n from tasks group by status"
        ) as cur:
            by_status = {r[0]: r[1] for r in await cur.fetchall()}

        facets = await self.evidence_facets()
        return {
            "reports": reports,
            "tasks_total": tasks_total,
            "tasks_by_status": by_status,
            "evidence_total": evidence_total,
            "claim_total": int(claim_total or 0),
            "high_conf_total": high_conf_total,
            "avg_evidence_per_report": round(evidence_total / reports, 1) if reports else 0,
            "avg_coverage": round(float(avg_coverage or 0), 4),
            "fact_accuracy": (
                round(high_conf_total / evidence_total * 100, 1) if evidence_total else 0
            ),
            "token_total": int(token_total or 0),
            "brand_distribution": facets["by_brand"],
            "source_type_distribution": facets["by_type"],
        }

    # --------------------------------------------------- v0.3.3 subscriptions

    async def create_subscription(
        self, sub_id: str, query: str, brands: list[str], interval_hours: int
    ) -> dict[str, Any]:
        await self.init()
        assert self._db is not None
        now = _now_iso()
        async with self._write_lock:
            await self._db.execute(
                "insert into subscriptions(sub_id, query, brands_json, interval_hours, "
                "created_at, last_run_at, last_task_id, run_count) "
                "values(?,?,?,?,?,NULL,NULL,0)",
                (sub_id, query, json.dumps(brands, ensure_ascii=False), int(interval_hours), now),
            )
            await self._db.commit()
        return await self.get_subscription(sub_id) or {"sub_id": sub_id}

    async def get_subscription(self, sub_id: str) -> dict[str, Any] | None:
        await self.init()
        assert self._db is not None
        async with self._db.execute(
            "select sub_id, query, brands_json, interval_hours, created_at, "
            "last_run_at, last_task_id, run_count from subscriptions where sub_id = ?",
            (sub_id,),
        ) as cur:
            row = await cur.fetchone()
        return None if row is None else _row_to_subscription(row)

    async def list_subscriptions(self) -> list[dict[str, Any]]:
        await self.init()
        assert self._db is not None
        async with self._db.execute(
            "select sub_id, query, brands_json, interval_hours, created_at, "
            "last_run_at, last_task_id, run_count from subscriptions order by created_at desc"
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_subscription(r) for r in rows]

    async def delete_subscription(self, sub_id: str) -> bool:
        await self.init()
        assert self._db is not None
        async with self._write_lock:
            cur = await self._db.execute("delete from subscriptions where sub_id = ?", (sub_id,))
            await self._db.commit()
            return cur.rowcount > 0

    async def mark_subscription_run(self, sub_id: str, task_id: str) -> None:
        """Record that a subscription run was triggered (v0.3.3)."""
        await self.init()
        assert self._db is not None
        async with self._write_lock:
            await self._db.execute(
                "update subscriptions set last_run_at = ?, last_task_id = ?, "
                "run_count = run_count + 1 where sub_id = ?",
                (_now_iso(), task_id, sub_id),
            )
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


def _row_to_subscription(row: Any) -> dict[str, Any]:
    return {
        "sub_id": row[0],
        "query": row[1],
        "brands": json.loads(row[2]) if row[2] else [],
        "interval_hours": row[3],
        "created_at": row[4],
        "last_run_at": row[5],
        "last_task_id": row[6],
        "run_count": row[7],
    }


def _node_id(n: Any) -> str:
    return getattr(n, "id", "") or (n.get("id") if isinstance(n, dict) else "") or ""


def _node_field(n: Any, name: str) -> str:
    if isinstance(n, dict):
        v = n.get(name, "")
    else:
        v = getattr(n, name, "")
    return "" if v is None else str(v)


def _node_status(n: Any) -> str:
    if isinstance(n, dict):
        s = n.get("status", "")
    else:
        s = getattr(n, "status", "")
    # Normalize Enum to its value (str(Enum) includes the class name on 3.11+).
    if hasattr(s, "value"):
        return str(s.value)
    return str(s) if s else ""


def _node_source(n: Any) -> str:
    return _node_field(n, "source")


def _classify_source(source: str) -> tuple[str, str]:
    """Derive (source_type, domain) from a node.source string.

    URL → ("web", host); known tool name → ("search_tool", ""); else ("other", "").
    """
    if source.startswith("http://") or source.startswith("https://"):
        try:
            from urllib.parse import urlparse

            host = urlparse(source).hostname or ""
            return ("web", host)
        except Exception:  # noqa: BLE001
            return ("web", "")
    if source and ("_search" in source or "_fetch" in source or source.endswith("_tool")):
        return ("search_tool", "")
    return ("other", "")


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()


__all__ = ["TaskProjectionStore"]
