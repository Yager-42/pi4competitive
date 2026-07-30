from __future__ import annotations

from pathlib import Path

import pytest

from competitive_app.adapter.out.persistence.learned_skill_store import SQLiteSkillStore
from competitive_app.adapter.out.persistence.workflow_skill_store import WorkflowSkillStore
from competitive_app.application.evolution.evolution_manager import EvolutionManager
from competitive_app.application.evolution.gates.score_delta_gate import ScoreDeltaGate
from competitive_app.application.evolution.post_task_observer import PostTaskObserver
from competitive_app.application.evolution.skill_files import SkillFiles
from competitive_app.application.evolution.skill_version_snapshot import SkillVersionSnapshot
from competitive_app.application.evolution.selector import SkillSelector
from competitive_app.application.evolution.parser import parse_skill_file
from competitive_app.domain.evolution.evolution_types import EvalResult, EvolutionContext
from competitive_app.domain.evolution.skill_types import SkillLineage, SkillRecord


def write(root: Path, name: str, marker: str) -> Path:
    path = root / name / "SKILL.md"; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: desc\nscope: plan\n---\n\n{marker}\n", encoding="utf-8")
    return path

@pytest.mark.asyncio
async def test_s1_four_scope_isolation_and_pin(tmp_path: Path) -> None:
    db = SQLiteSkillStore(tmp_path / "app.db"); bindings = WorkflowSkillStore(tmp_path / "app.db")
    await db.init(); await bindings.init()
    plan = parse_skill_file(write(tmp_path, "plan", "PLAN")); await db.register(plan, scope="plan")
    snapshot = SkillVersionSnapshot(selector=SkillSelector(db), skill_store=db, binding_store=bindings)
    first = await snapshot.ensure_scope("task", "plan", "x")
    second = await snapshot.ensure_scope("task", "plan", "changed")
    assert [r.skill_id for r in first] == [r.skill_id for r in second]
    await db.close(); await bindings.close()

@pytest.mark.asyncio
async def test_s3_captured_observation_requires_solution_and_transferability(tmp_path: Path) -> None:
    bindings = WorkflowSkillStore(tmp_path / "app.db"); await bindings.init()
    observer = PostTaskObserver(observation_store=bindings)
    assert await observer.observe(task_id="t", status="completed", scope="plan", problem_signature="problem", solution="", transferability="", solution_demonstrated=False) is None
    context = await observer.observe(task_id="t2", status="completed", scope="plan", problem_signature="new problem", solution="worked solution", transferability="general", solution_demonstrated=True, suggested_name="captured")
    assert context and context.evolution_type == "CAPTURED"
    await bindings.close()

@pytest.mark.asyncio
async def test_s4_aborted_is_ignored(tmp_path: Path) -> None:
    bindings = WorkflowSkillStore(tmp_path / "app.db"); await bindings.init()
    observer = PostTaskObserver(observation_store=bindings)
    assert await observer.observe(task_id="aborted", status="aborted", scope="write", problem_signature="p", solution="s", transferability="t", solution_demonstrated=True) is None
    assert await bindings.list_observations(unconsumed_only=False) == []
    await bindings.close()
