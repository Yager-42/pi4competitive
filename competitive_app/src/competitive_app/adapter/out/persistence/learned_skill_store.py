"""Async SQLite learned Skill store adapted from Poirot ``skill/store.py``.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/store.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: aiosqlite + existing ``data/app.db`` and asyncio write lock; the
original tables, fields, version-DAG pointer, metrics and CRUD semantics remain.
Workflow scope/task observations are in companion tables and do not alter the
Poirot ``skill_records`` fields.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from ....domain.evolution.eval_types import EvalRun, SkillJudgment, TaskQualityScore
from ....domain.evolution.evolution_types import EvolutionRecord
from ....domain.evolution.skill_types import SkillHealth, SkillLineage, SkillMetrics, SkillRecord


_BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_records (
 skill_id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL,
 content_hash TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1,
 generation INTEGER NOT NULL DEFAULT 0, origin TEXT NOT NULL DEFAULT 'IMPORTED',
 created_by TEXT, description TEXT NOT NULL DEFAULT '', allowed_tools TEXT NOT NULL DEFAULT '[]',
 enabled INTEGER NOT NULL DEFAULT 1, total_selections INTEGER NOT NULL DEFAULT 0,
 total_applied INTEGER NOT NULL DEFAULT 0, total_completions INTEGER NOT NULL DEFAULT 0,
 total_fallbacks INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, last_updated TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_records_name ON skill_records(name);
CREATE INDEX IF NOT EXISTS idx_skill_records_active ON skill_records(is_active);
CREATE TABLE IF NOT EXISTS skill_lineage_parents(
 skill_id TEXT NOT NULL, parent_skill_id TEXT NOT NULL,
 PRIMARY KEY(skill_id,parent_skill_id)
);
CREATE TABLE IF NOT EXISTS skill_judgments(
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, skill_id TEXT NOT NULL,
 applied INTEGER, task_completed INTEGER NOT NULL DEFAULT 0, ts TEXT NOT NULL, note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_skill_judgments_skill ON skill_judgments(skill_id, ts);
CREATE TABLE IF NOT EXISTS skill_evolutions(
 evolution_id TEXT PRIMARY KEY, skill_name TEXT NOT NULL, evolution_type TEXT NOT NULL,
 trigger TEXT NOT NULL, baseline_id TEXT, candidate_id TEXT NOT NULL,
 failure_focus TEXT NOT NULL DEFAULT '', mutation_diff TEXT NOT NULL DEFAULT '',
 eval_score REAL NOT NULL DEFAULT 0.0, gate_decision TEXT NOT NULL,
 created_version_id TEXT, timestamp TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_skill_evolutions_name ON skill_evolutions(skill_name,timestamp);
CREATE TABLE IF NOT EXISTS skill_eval_judgments(
 judgment_id TEXT PRIMARY KEY, skill_id TEXT NOT NULL, skill_name TEXT NOT NULL,
 task_id TEXT, skill_applied INTEGER NOT NULL, deviation_note TEXT NOT NULL DEFAULT '', timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_quality_scores(
 score_id TEXT PRIMARY KEY, task_id TEXT, task_completion REAL NOT NULL,
 response_quality REAL NOT NULL, efficiency REAL NOT NULL, tool_usage REAL NOT NULL,
 overall_score REAL NOT NULL, rationale TEXT NOT NULL DEFAULT '', timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skill_eval_runs(
 eval_run_id TEXT PRIMARY KEY, eval_layer TEXT NOT NULL, skill_ids TEXT NOT NULL,
 candidate_id TEXT, baseline_id TEXT, result_json TEXT NOT NULL DEFAULT '', timestamp TEXT NOT NULL
);
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _close_cursor(cursor: Any) -> None:
    close = getattr(cursor, "close", None)
    if close is not None:
        result = close()
        if hasattr(result, "__await__"):
            await result


class SQLiteSkillStore:
    """Async app.db implementation of Poirot's SQLiteSkillStore contract."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()

    async def init(self) -> None:
        if self._db is not None:
            return
        async with self._init_lock:
            if self._db is not None:
                return
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            db = await aiosqlite.connect(self._db_path)
            db.row_factory = aiosqlite.Row
            await db.executescript(_BASE_SCHEMA)
            # Legacy databases may contain duplicate task scores; retain the
            # latest inserted row before enforcing the one-score-per-task index.
            await db.execute(
                """DELETE FROM task_quality_scores
                WHERE task_id IS NOT NULL AND rowid NOT IN (
                    SELECT MAX(rowid) FROM task_quality_scores
                    WHERE task_id IS NOT NULL GROUP BY task_id
                )"""
            )
            await db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_task_quality_scores_task "
                "ON task_quality_scores(task_id) WHERE task_id IS NOT NULL"
            )
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

    async def register(self, record: SkillRecord, scope: str | None = None) -> str:
        db = await self._ready()
        now = _now_iso()
        async with self._write_lock:
            await db.execute(
                """INSERT OR IGNORE INTO skill_records
                (skill_id,name,path,content_hash,is_active,generation,origin,created_by,description,
                 allowed_tools,enabled,created_at,last_updated)
                VALUES (?,?,?,?,1,?,?,?,?,?,?,?,?)""",
                (record.skill_id, record.name, record.path, record.content_hash,
                 record.lineage.generation, record.lineage.origin, record.lineage.created_by,
                 record.description, json.dumps(list(record.allowed_tools)), int(record.enabled), now, now),
            )
            for parent in record.lineage.parent_skill_ids:
                await db.execute(
                    "INSERT OR IGNORE INTO skill_lineage_parents(skill_id,parent_skill_id) VALUES(?,?)",
                    (record.skill_id, parent),
                )
            if scope is not None:
                await self._set_scope_locked(db, record.skill_id, scope, record.path, now)
            await db.commit()
        return record.skill_id

    async def upsert(self, record: SkillRecord, scope: str | None = None) -> str:
        db = await self._ready()
        now = _now_iso()
        async with self._write_lock:
            cur = await db.execute("SELECT 1 FROM skill_records WHERE skill_id=?", (record.skill_id,))
            exists = await cur.fetchone()
            await _close_cursor(cur)
            if exists is None:
                await db.execute(
                    """INSERT INTO skill_records(skill_id,name,path,content_hash,is_active,generation,origin,
                    created_by,description,allowed_tools,enabled,created_at,last_updated)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (record.skill_id, record.name, record.path, record.content_hash, int(record.is_active),
                     record.lineage.generation, record.lineage.origin, record.lineage.created_by,
                     record.description, json.dumps(list(record.allowed_tools)), int(record.enabled), now, now),
                )
            else:
                await db.execute(
                    """UPDATE skill_records SET name=?,path=?,content_hash=?,is_active=?,
                    generation=?,origin=?,created_by=?,description=?,allowed_tools=?,enabled=?,last_updated=?
                    WHERE skill_id=?""",
                    (record.name, record.path, record.content_hash, int(record.is_active),
                     record.lineage.generation, record.lineage.origin, record.lineage.created_by,
                     record.description, json.dumps(list(record.allowed_tools)), int(record.enabled),
                     now, record.skill_id),
                )
            for parent in record.lineage.parent_skill_ids:
                await db.execute("INSERT OR IGNORE INTO skill_lineage_parents VALUES(?,?)", (record.skill_id, parent))
            if scope is not None:
                await self._set_scope_locked(db, record.skill_id, scope, record.path, now)
            await db.commit()
        return record.skill_id

    async def discover(self, dirs: list[Path], origin: str = "IMPORTED") -> list[SkillRecord]:
        from ....application.evolution.parser import parse_skill_file_async, scope_from_skill_file
        result: list[SkillRecord] = []
        for root_value in dirs:
            root = Path(root_value)
            if root.is_file():
                paths = [root]
            else:
                manifest = root.parent / "package.json"
                paths: list[Path]
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                    entries = data.get("pi", {}).get("skills")
                    paths = [manifest.parent / str(entry) for entry in entries] if isinstance(entries, list) else []
                except FileNotFoundError:
                    paths = sorted(root.rglob("SKILL.md"))
                except (OSError, json.JSONDecodeError, AttributeError):
                    paths = []
            for path in paths:
                if not path.is_file() or path.name != "SKILL.md":
                    continue
                record = await parse_skill_file_async(path, origin)
                await self.upsert(record, scope=scope_from_skill_file(path))
                result.append(record)
        return result

    async def get(self, skill_id: str) -> SkillRecord | None:
        db = await self._ready()
        async with db.execute("SELECT * FROM skill_records WHERE skill_id=?", (skill_id,)) as cur:
            row = await cur.fetchone()
        return await self._row_to_record(row) if row is not None else None

    async def get_active(self, name: str, scope: str | None = None) -> SkillRecord | None:
        db = await self._ready()
        query = "SELECT * FROM skill_records WHERE name=? AND is_active=1"
        args: list[Any] = [name]
        if scope is not None:
            query += " AND skill_id IN (SELECT skill_id FROM workflow_skill_metadata WHERE scope=?)"
            args.append(scope)
        async with db.execute(query, args) as cur:
            row = await cur.fetchone()
        return await self._row_to_record(row) if row is not None else None

    async def list_active(self, scope: str | None = None) -> list[SkillRecord]:
        db = await self._ready()
        query = "SELECT * FROM skill_records WHERE is_active=1"
        args: list[Any] = []
        if scope is not None:
            query += " AND skill_id IN (SELECT skill_id FROM workflow_skill_metadata WHERE scope=?)"
            args.append(scope)
        query += " ORDER BY name, generation"
        async with db.execute(query, args) as cur:
            rows = await cur.fetchall()
        return [record for row in rows if (record := await self._row_to_record(row)) is not None]

    async def get_scope(self, skill_id: str) -> str | None:
        db = await self._ready()
        async with db.execute("SELECT scope FROM workflow_skill_metadata WHERE skill_id=?", (skill_id,)) as cur:
            row = await cur.fetchone()
        return row[0] if row else None

    async def set_enabled(self, skill_id: str, enabled: bool) -> bool:
        db = await self._ready()
        async with self._write_lock:
            cur = await db.execute("UPDATE skill_records SET enabled=?,last_updated=? WHERE skill_id=?",
                                   (int(enabled), _now_iso(), skill_id))
            await db.commit()
        return cur.rowcount > 0

    async def create_version(self, parent_id: str, record: SkillRecord, origin: str | None = None) -> str:
        db = await self._ready()
        now = _now_iso()
        async with self._write_lock:
            cur = await db.execute("SELECT 1 FROM skill_records WHERE skill_id=?", (record.skill_id,))
            if await cur.fetchone() is not None:
                raise ValueError(f"skill_id already exists: {record.skill_id}")
            await db.execute(
                """INSERT INTO skill_records(skill_id,name,path,content_hash,is_active,generation,origin,created_by,
                description,allowed_tools,enabled,created_at,last_updated)
                VALUES(?,?,?,?,1,?,?,?,?,?,?,?,?)""",
                (record.skill_id, record.name, record.path, record.content_hash, record.lineage.generation,
                 origin or record.lineage.origin, record.lineage.created_by, record.description,
                 json.dumps(list(record.allowed_tools)), int(record.enabled), now, now),
            )
            if parent_id:
                await db.execute("INSERT OR IGNORE INTO skill_lineage_parents VALUES(?,?)", (record.skill_id, parent_id))
            await db.execute("UPDATE skill_records SET is_active=0 WHERE name=? AND skill_id<>?",
                             (record.name, record.skill_id))
            await db.commit()
        return record.skill_id

    async def get_versions(self, name: str) -> list[SkillRecord]:
        db = await self._ready()
        async with db.execute("SELECT * FROM skill_records WHERE name=? ORDER BY generation ASC", (name,)) as cur:
            rows = await cur.fetchall()
        return [record for row in rows if (record := await self._row_to_record(row)) is not None]

    async def rollback(self, skill_id: str) -> None:
        db = await self._ready()
        async with self._write_lock:
            async with db.execute("SELECT name FROM skill_records WHERE skill_id=?", (skill_id,)) as cur:
                row = await cur.fetchone()
            if row is None:
                return
            await db.execute("UPDATE skill_records SET is_active=1,last_updated=? WHERE skill_id=?", (_now_iso(), skill_id))
            await db.execute("UPDATE skill_records SET is_active=0 WHERE name=? AND skill_id<>?", (row[0], skill_id))
            await db.commit()

    async def record_selection(self, skill_id: str) -> None:
        db = await self._ready()
        async with self._write_lock:
            await db.execute("UPDATE skill_records SET total_selections=total_selections+1,last_updated=? WHERE skill_id=?",
                             (_now_iso(), skill_id))
            await db.commit()

    async def record_outcome(self, skill_id: str, run_id: str, applied: bool | None,
                             task_completed: bool, note: str = "") -> None:
        db = await self._ready()
        async with self._write_lock:
            async with db.execute("SELECT 1 FROM skill_records WHERE skill_id=?", (skill_id,)) as cur:
                if await cur.fetchone() is None:
                    return
            inc_applied = int(applied is True)
            inc_completion = int(applied is True and task_completed)
            inc_fallback = int(applied is False and not task_completed)
            await db.execute(
                """UPDATE skill_records SET total_applied=total_applied+?,total_completions=total_completions+?,
                total_fallbacks=total_fallbacks+?,last_updated=? WHERE skill_id=?""",
                (inc_applied, inc_completion, inc_fallback, _now_iso(), skill_id),
            )
            await db.execute("INSERT INTO skill_judgments(run_id,skill_id,applied,task_completed,ts,note) VALUES(?,?,?,?,?,?)",
                             (run_id, skill_id, None if applied is None else int(applied), int(task_completed), _now_iso(), note))
            await db.commit()

    async def get_metrics(self, skill_id: str) -> SkillMetrics | None:
        db = await self._ready()
        async with db.execute("SELECT total_selections,total_applied,total_completions,total_fallbacks FROM skill_records WHERE skill_id=?", (skill_id,)) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        selections, applied, completions, fallbacks = map(int, row)
        return SkillMetrics(skill_id, selections, applied, completions, fallbacks,
                            applied / selections if selections else 0.0,
                            completions / applied if applied else 0.0,
                            completions / selections if selections else 0.0,
                            fallbacks / selections if selections else 0.0)

    async def get_top_skills(self, n: int, metric: str = "effective_rate", min_selections: int = 5) -> list[SkillRecord]:
        records = [r for r in await self.list_active() if r.total_selections >= min_selections]
        if metric not in {"effective_rate", "applied_rate", "completion_rate", "fallback_rate"}:
            raise ValueError(f"unsupported metric: {metric}")
        return sorted(records, key=lambda record: getattr(record, metric), reverse=True)[:n]

    async def health_check(self, threshold: float = 0.4, min_selections: int = 5) -> list[SkillHealth]:
        result: list[SkillHealth] = []
        for record in await self.list_active():
            result.append(SkillHealth(record.skill_id, record.name, record.effective_rate,
                                      record.fallback_rate, record.total_selections,
                                      record.total_selections >= min_selections and record.effective_rate < threshold))
        return result

    async def record_evolution(self, record: EvolutionRecord) -> str:
        db = await self._ready()
        async with self._write_lock:
            await db.execute(
                """INSERT OR REPLACE INTO skill_evolutions(evolution_id,skill_name,evolution_type,trigger,baseline_id,
                candidate_id,failure_focus,mutation_diff,eval_score,gate_decision,created_version_id,timestamp)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (record.evolution_id, record.skill_name, record.evolution_type, record.trigger, record.baseline_id,
                 record.candidate_id, record.failure_focus, record.mutation_diff, record.eval_score,
                 record.gate_decision, record.created_version_id, record.timestamp or _now_iso()),
            )
            await db.commit()
        return record.evolution_id

    async def get_evolution_history(self, skill_name: str, limit: int = 20) -> list[dict[str, Any]]:
        db = await self._ready()
        async with db.execute("SELECT * FROM skill_evolutions WHERE skill_name=? ORDER BY timestamp DESC LIMIT ?", (skill_name, limit)) as cur:
            rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def save_judgment(self, judgment: SkillJudgment) -> str:
        db = await self._ready()
        async with self._write_lock:
            await db.execute("""INSERT OR REPLACE INTO skill_eval_judgments
                (judgment_id,skill_id,skill_name,task_id,skill_applied,deviation_note,timestamp)
                VALUES(?,?,?,?,?,?,?)""",
                             (judgment.judgment_id, judgment.skill_id, judgment.skill_name, judgment.task_id,
                              int(judgment.skill_applied), judgment.deviation_note, judgment.timestamp or _now_iso()))
            await db.commit()
        return judgment.judgment_id

    async def get_judgments(self, skill_id: str, limit: int = 20) -> list[SkillJudgment]:
        db = await self._ready()
        async with db.execute("SELECT * FROM skill_eval_judgments WHERE skill_id=? ORDER BY timestamp DESC LIMIT ?", (skill_id, limit)) as cur:
            rows = await cur.fetchall()
        return [SkillJudgment(r["judgment_id"], r["skill_id"], r["skill_name"], r["task_id"] or "",
                              bool(r["skill_applied"]), r["deviation_note"], r["timestamp"]) for r in rows]

    async def save_task_score(self, score: TaskQualityScore) -> str:
        db = await self._ready()
        async with self._write_lock:
            values = (
                score.score_id, score.task_id, score.task_completion, score.response_quality,
                score.efficiency, score.tool_usage, score.overall_score, score.rationale,
                score.timestamp or _now_iso(),
            )
            if score.task_id:
                # Replace the task's authoritative row, including legacy DBs
                # created before the unique task index existed.
                await db.execute(
                    "DELETE FROM task_quality_scores WHERE task_id=? AND score_id<>?",
                    (score.task_id, score.score_id),
                )
            await db.execute("""INSERT OR REPLACE INTO task_quality_scores
                (score_id,task_id,task_completion,response_quality,efficiency,tool_usage,overall_score,rationale,timestamp)
                VALUES(?,?,?,?,?,?,?,?,?)""", values)
            await db.commit()
        return score.score_id

    async def get_task_score(self, task_id: str) -> TaskQualityScore | None:
        db = await self._ready()
        async with db.execute(
            "SELECT * FROM task_quality_scores WHERE task_id=? "
            "ORDER BY timestamp DESC, rowid DESC LIMIT 1", (task_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return TaskQualityScore(row["score_id"], row["task_id"] or "", row["task_completion"], row["response_quality"],
                                row["efficiency"], row["tool_usage"], row["overall_score"], row["rationale"], row["timestamp"])

    async def save_eval_run(self, run: EvalRun) -> str:
        db = await self._ready()
        async with self._write_lock:
            await db.execute("""INSERT OR REPLACE INTO skill_eval_runs
                (eval_run_id,eval_layer,skill_ids,candidate_id,baseline_id,result_json,timestamp)
                VALUES(?,?,?,?,?,?,?)""",
                             (run.eval_run_id, run.eval_layer, json.dumps(list(run.skill_ids)), run.candidate_id,
                              run.baseline_id, run.result_json, run.timestamp or _now_iso()))
            await db.commit()
        return run.eval_run_id

    async def delete_task_references(self, task_id: str) -> None:
        """Delete bindings/unconsumed observations; de-identify retained eval rows."""
        db = await self._ready()
        async with self._write_lock:
            await db.execute("DELETE FROM skill_task_bindings WHERE task_id=?", (task_id,))
            await db.execute("DELETE FROM skill_evidence_refs WHERE observation_id IN (SELECT observation_id FROM skill_observations WHERE task_id=? AND consumed=0)", (task_id,))
            await db.execute("DELETE FROM skill_observations WHERE task_id=? AND consumed=0", (task_id,))
            await db.execute("UPDATE skill_eval_judgments SET task_id=NULL WHERE task_id=?", (task_id,))
            await db.execute("UPDATE skill_judgments SET run_id='deleted' WHERE run_id=?", (task_id,))
            await db.execute("UPDATE task_quality_scores SET task_id=NULL WHERE task_id=?", (task_id,))
            await db.commit()

    async def _set_scope_locked(self, db: aiosqlite.Connection, skill_id: str, scope: str, path: str, now: str) -> None:
        await db.execute("""INSERT INTO workflow_skill_metadata(skill_id,scope,package_path,created_at,updated_at)
            VALUES(?,?,?,?,?) ON CONFLICT(skill_id) DO UPDATE SET scope=excluded.scope,package_path=excluded.package_path,updated_at=excluded.updated_at""",
                       (skill_id, scope, path, now, now))

    async def _row_to_record(self, row: Any) -> SkillRecord:
        db = await self._ready()
        async with db.execute("SELECT parent_skill_id FROM skill_lineage_parents WHERE skill_id=? ORDER BY parent_skill_id", (row["skill_id"],)) as cur:
            parents = tuple(r[0] for r in await cur.fetchall())
        try:
            tools = tuple(json.loads(row["allowed_tools"] or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            tools = ()
        return SkillRecord(
            skill_id=row["skill_id"], name=row["name"], path=row["path"], content_hash=row["content_hash"],
            is_active=bool(row["is_active"]),
            lineage=SkillLineage(parents, row["generation"], row["origin"], row["content_hash"], row["created_by"]),
            description=row["description"], allowed_tools=tools, enabled=bool(row["enabled"]),
            total_selections=row["total_selections"], total_applied=row["total_applied"],
            total_completions=row["total_completions"], total_fallbacks=row["total_fallbacks"],
            created_at=row["created_at"], last_updated=row["last_updated"],
        )


__all__ = ["SQLiteSkillStore"]
