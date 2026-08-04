"""Focused regressions for persistence and observability known issues."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from competitive_app.adapter.out.observability import redact_payload
from competitive_app.adapter.out.observability.events import utc_now_iso
from competitive_app.adapter.out.observability.run_journal import RunJournal
from competitive_app.adapter.out.persistence.learned_skill_store import SQLiteSkillStore
from competitive_app.adapter.out.persistence.socm_store import SocmStore
from competitive_app.adapter.out.persistence.task_projection_store import TaskProjectionStore
from competitive_app.adapter.out.persistence.workflow_skill_store import WorkflowSkillStore
from competitive_app.domain.evolution.eval_types import TaskQualityScore
from competitive_app.domain.evolution.skill_types import SkillLineage, SkillRecord
from competitive_app.domain.socm.state import SOCMState


def test_redaction_covers_camel_case_headers_and_nested_values() -> None:
    payload = {
        "apiKey": "one",
        "AUTHORIZATION_HEADER": "Bearer two",
        "client-secret": "three",
        "nested": [{"accessToken": "four"}],
        "safe": "visible",
    }
    redacted = redact_payload(payload)
    assert redacted["apiKey"] == "[REDACTED]"
    assert redacted["AUTHORIZATION_HEADER"] == "[REDACTED]"
    assert redacted["client-secret"] == "[REDACTED]"
    assert redacted["nested"][0]["accessToken"] == "[REDACTED]"
    assert redacted["safe"] == "visible"


def test_utc_now_iso_is_zero_offset() -> None:
    assert datetime.fromisoformat(utc_now_iso()).utcoffset().total_seconds() == 0


def test_run_journal_is_one_json_object_per_line(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    journal = RunJournal("run", path)
    journal.append("run.started", {"message": "line\nvalue"})
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event_type"] == "run.started"


@pytest.mark.asyncio
async def test_evidence_ids_are_namespaced_by_task(tmp_path) -> None:
    store = TaskProjectionStore(str(tmp_path / "app.db"))
    try:
        node = SimpleNamespace(id="deadbeef", status="active", entity="A", attribute="price", value="$1", finding="", source="https://a.example", confidence=0.9)
        await store.index_evidences("task-a", [node], "2026-01-01T00:00:00+00:00")
        await store.index_evidences("task-b", [node], "2026-01-01T00:00:00+00:00")
        rows = await store.query_evidences()
        assert {row["evidence_id"] for row in rows} == {"task-a:deadbeef", "task-b:deadbeef"}
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_upsert_updates_authoritative_skill_metadata(tmp_path) -> None:
    store = SQLiteSkillStore(tmp_path / "app.db")
    try:
        first = SkillRecord("s", "old", "/old", "h1")
        await store.upsert(first)
        replacement = SkillRecord(
            "s", "new", "/new", "h2", False,
            SkillLineage((), 4, "GENERATED", "h2", "author"),
            "description", ("tool",), False,
        )
        await store.upsert(replacement)
        loaded = await store.get("s")
        assert loaded is not None
        assert (loaded.name, loaded.path, loaded.content_hash, loaded.is_active) == ("new", "/new", "h2", False)
        assert (loaded.lineage.generation, loaded.lineage.origin, loaded.lineage.created_by) == (4, "GENERATED", "author")
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_task_scores_are_unique_and_latest_is_returned(tmp_path) -> None:
    store = SQLiteSkillStore(tmp_path / "app.db")
    try:
        old = TaskQualityScore("score-old", "task", 0.1, 0.1, 0.1, 0.1, 0.1, timestamp="2026-01-01T00:00:00+00:00")
        new = TaskQualityScore("score-new", "task", 0.9, 0.9, 0.9, 0.9, 0.9, timestamp="2026-01-02T00:00:00+00:00")
        await store.save_task_score(old)
        await store.save_task_score(new)
        loaded = await store.get_task_score("task")
        assert loaded is not None and loaded.score_id == "score-new" and loaded.overall_score == 0.9
        async with store._db.execute("SELECT count(*) FROM task_quality_scores WHERE task_id='task'") as cur:  # type: ignore[union-attr]
            assert (await cur.fetchone())[0] == 1
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_socm_delete_coordinates_and_retains_sidecar(tmp_path) -> None:
    store = SocmStore(tmp_path)
    await store.save("session", SOCMState(intent="x"))
    lock = await store._lock_for("session")
    await store.delete("session")
    assert "session" in store._locks and store._locks["session"] is lock
    assert (tmp_path / "session" / ".search_state.json.lock").is_file()
    assert not await store.exists("session")


@pytest.mark.asyncio
async def test_observation_consumption_is_compare_and_set(tmp_path) -> None:
    store = WorkflowSkillStore(tmp_path / "app.db")
    try:
        await store.add_observation(observation_id="obs", task_id="task", scope="plan", problem_signature="p")
        results = await asyncio.gather(store.mark_consumed("obs"), store.mark_consumed("obs"))
        assert sorted(results) == [False, True]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_restore_task_cas_includes_updated_at(tmp_path) -> None:
    """Startup compensation must not clobber a row whose metadata changed
    while status stayed pending: the snapshot's updated_at is part of CAS."""
    store = TaskProjectionStore(str(tmp_path / "app.db"))
    try:
        await store.create_task(
            task_id="t1", query="q", status="pending", metadata={"a": 1},
            projection={}, session_id="s1",
        )
        task = await store.get_task("t1")
        assert task is not None
        # Simulate a concurrent writer that updates metadata without touching
        # status or session_id.
        await store.update_task_metadata("t1", {"a": 2})
        fresh = await store.get_task("t1")
        assert fresh is not None
        assert await store.restore_task_if_current(
            task, expected_status="pending", expected_session_id="s1"
        ) is False
        # The newer row is untouched by the failed compensation.
        after = await store.get_task("t1")
        assert after is not None
        assert after["metadata"] == {"a": 2}
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_restore_task_cas_succeeds_with_matching_snapshot(tmp_path) -> None:
    store = TaskProjectionStore(str(tmp_path / "app.db"))
    try:
        await store.create_task(
            task_id="t1", query="q", status="pending", metadata={"a": 1},
            projection={}, session_id="s1",
        )
        task = await store.get_task("t1")
        assert task is not None
        assert await store.restore_task_if_current(
            task, expected_status="pending", expected_session_id="s1"
        ) is True
    finally:
        await store.close()
