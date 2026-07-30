from __future__ import annotations

import json
from pathlib import Path

import pytest

from competitive_app.application.evolution.skill_metrics import SkillMetricsRecorder
from competitive_app.application.evolution.config import load_skill_config
from competitive_app.wiring import build_application_state, load_config_from_env


@pytest.mark.asyncio
async def test_enabled_app_bootstraps_learned_skills_and_app_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "learned"
    skill_dir = root / "skills" / "plan-tip"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: plan-tip\ndescription: plan guidance\nscope: plan\n---\n\nPLAN_INJECT\n", encoding="utf-8"
    )
    monkeypatch.setenv("USE_FAUX", "1")
    monkeypatch.setenv("SESSIONS_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("APP_DB", str(tmp_path / "app.db"))
    monkeypatch.setenv("SESSIONS_CWD", "test")
    monkeypatch.setenv("CAPABILITY_PACKAGES_ENABLED", "echo_example")
    monkeypatch.setenv("WORKFLOW_SKILL_ENABLED", "1")
    monkeypatch.setenv("WORKFLOW_SKILL_ROOT", str(root))
    config = load_config_from_env()
    state = await build_application_state(config)
    try:
        assert state.skill_selector is not None and state.skill_snapshot is not None
        records = await state.skill_store.list_active("plan")
        assert [record.name for record in records] == ["plan-tip"]
        names = {row[0] for row in await _tables(state.config.app_db)}
        assert {"skill_records", "workflow_skill_metadata", "skill_task_bindings", "skill_observations"} <= names
    finally:
        await state.shutdown()


async def _tables(path: str):
    import aiosqlite
    db = await aiosqlite.connect(path)
    try:
        async with db.execute("select name from sqlite_master where type='table'") as cur:
            return await cur.fetchall()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_aborted_tasks_do_not_write_skill_outcomes(tmp_path: Path) -> None:
    from competitive_app.adapter.out.persistence.learned_skill_store import SQLiteSkillStore
    from competitive_app.domain.evolution.skill_types import SkillRecord
    store = SQLiteSkillStore(tmp_path / "app.db"); await store.init()
    record = SkillRecord("x", "x", str(tmp_path / "SKILL.md"), "h")
    await store.register(record, scope="plan"); await store.record_selection("x")
    await SkillMetricsRecorder(store).record_outcome(task_id="t", status="aborted", applied_by_skill={"x": False})
    metrics = await store.get_metrics("x")
    assert metrics and metrics.applied == 0 and metrics.fallbacks == 0
    await store.close()
