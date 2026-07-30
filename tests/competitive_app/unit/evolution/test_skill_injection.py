from __future__ import annotations

from pathlib import Path

import pytest

from competitive_app.adapter.out.persistence.learned_skill_store import SQLiteSkillStore
from competitive_app.application.evolution.injector import build_injection_text
from competitive_app.application.evolution.selector import SkillSelector
from competitive_app.application.evolution.skill_version_snapshot import SkillVersionSnapshot
from competitive_app.application.evolution.stage_skill_composer import StageSkillComposer
from competitive_app.adapter.out.persistence.workflow_skill_store import WorkflowSkillStore
from competitive_app.application.evolution.parser import parse_skill_file


def _write_skill(root: Path, name: str, body: str) -> Path:
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\nname: {name}\ndescription: {name} desc\n---\n\n{body}\n", encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_scope_selection_binding_and_resume(tmp_path: Path) -> None:
    db = SQLiteSkillStore(tmp_path / "app.db")
    bindings = WorkflowSkillStore(tmp_path / "app.db")
    await db.init(); await bindings.init()
    plan = parse_skill_file(_write_skill(tmp_path, "plan-only", "PLAN_MARKER"))
    write = parse_skill_file(_write_skill(tmp_path, "write-only", "WRITE_MARKER"))
    await db.register(plan, scope="plan")
    await db.register(write, scope="write")
    selector = SkillSelector(db)
    snapshot = SkillVersionSnapshot(selector=selector, skill_store=db, binding_store=bindings)
    selected = await snapshot.ensure_scope("task-1", "plan", "research")
    assert [s.name for s in selected] == ["plan-only"]
    assert "PLAN_MARKER" in build_injection_text(selected)
    assert "WRITE_MARKER" not in build_injection_text(selected)
    # Promotion can change active state, but existing task uses its bound id.
    again = await snapshot.ensure_scope("task-1", "plan", "different")
    assert [s.skill_id for s in again] == [s.skill_id for s in selected]
    assert (await bindings.get_bindings("task-1", "plan")) == [plan.skill_id]
    await db.close(); await bindings.close()

@pytest.mark.asyncio
async def test_empty_scope_binding_is_not_reselected(tmp_path: Path) -> None:
    db = SQLiteSkillStore(tmp_path / "app.db"); bindings = WorkflowSkillStore(tmp_path / "app.db")
    await db.init(); await bindings.init()
    class Selector:
        def __init__(self): self.calls = 0
        async def select_for_scope(self, *_args, **_kwargs): self.calls += 1; return []
    selector = Selector()
    snapshot = SkillVersionSnapshot(selector=selector, skill_store=db, binding_store=bindings)
    assert await snapshot.ensure_scope("empty", "plan", "first") == []
    assert await snapshot.ensure_scope("empty", "plan", "resume") == []
    assert selector.calls == 1
    await db.close(); await bindings.close()


def test_stage_composer_keeps_base_and_full_skill() -> None:
    class Record:
        name = "x"
        description = "x desc"
        path = ""
    assert StageSkillComposer().compose("BASE", []) == "BASE"
