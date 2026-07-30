from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from competitive_app.adapter.out.persistence.learned_skill_store import SQLiteSkillStore
from competitive_app.application.evolution.cycle_runner import EvolutionCycleRunner
from competitive_app.application.evolution.evolution_manager import EvolutionManager
from competitive_app.application.evolution.gates.score_delta_gate import ScoreDeltaGate
from competitive_app.application.evolution.skill_files import SkillFiles
from competitive_app.application.evolution.parser import parse_skill_file
from competitive_app.domain.evolution.evolution_types import EvalContext, EvalResult, EvolutionContext
from competitive_app.domain.evolution.skill_types import SkillLineage, SkillRecord
from competitive_app.application.evolution.gates.git_ratchet import GitRatchet


def make(path: Path, name: str, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: desc\n---\n\n{body}\n", encoding="utf-8")
    return path


class Focuser:
    async def focus(self, ctx, store): return ctx

class Mutator:
    def __init__(self, path): self.path = path
    async def mutate(self, ctx, llm=None):
        rec = SkillRecord("candidate__v0_abcd1234", "candidate", str(self.path), "hash", False,
                          SkillLineage((), 0, "CAPTURED", "hash", "test"), "desc", ())
        return rec, "+ candidate"

class Bridge:
    async def evaluate(self, ctx): return EvalResult(1.0)

@pytest.mark.asyncio
async def test_manager_accepts_and_projects_manifest(tmp_path: Path) -> None:
    store = SQLiteSkillStore(tmp_path / "app.db"); await store.init()
    candidate_path = make(tmp_path / "learned" / "skills" / "candidate__v0_abcd1234" / "SKILL.md", "candidate", "MUST work")
    files = SkillFiles(tmp_path / "learned", store)
    manager = EvolutionManager(store, [], Focuser(), Mutator(candidate_path), Bridge(), ScoreDeltaGate(), skill_files=files)
    record = await manager.run_context(EvolutionContext("CAPTURE", "CAPTURED", None, capture_pattern="pattern", suggested_name="candidate", scope="plan"))
    assert record and record.created_version_id == "candidate__v0_abcd1234"
    active = await store.get_active("candidate")
    assert active and active.skill_id == record.created_version_id
    manifest = (tmp_path / "learned" / "package.json").read_text()
    assert "skills/candidate__v0_abcd1234/SKILL.md" in manifest
    await store.close()

@pytest.mark.asyncio
async def test_cycle_runner_serializes_manager(tmp_path: Path) -> None:
    class Manager:
        def __init__(self): self.calls = 0
        async def run_cycle(self): self.calls += 1; return [self.calls]
    manager = Manager(); runner = EvolutionCycleRunner(manager)
    assert await runner.run_cycle() == [1]
    assert manager.calls == 1

@pytest.mark.asyncio
async def test_rejected_candidate_deleted_after_record(tmp_path: Path) -> None:
    store = SQLiteSkillStore(tmp_path / "app.db"); await store.init()
    candidate_path = make(tmp_path / "learned" / "skills" / "candidate__v0_reject1234" / "SKILL.md", "candidate", "")
    files = SkillFiles(tmp_path / "learned", store)
    class RejectBridge:
        async def evaluate(self, ctx): return EvalResult(0.0, hard_failures=("nonempty",), recommendation="reject")
    manager = EvolutionManager(store, [], Focuser(), Mutator(candidate_path), RejectBridge(), ScoreDeltaGate(), skill_files=files)
    record = await manager.run_context(EvolutionContext("CAPTURE", "CAPTURED", None, capture_pattern="p", suggested_name="candidate"))
    assert record and record.gate_decision == "reject"
    assert not candidate_path.exists() and not candidate_path.parent.exists()
    assert await store.get_evolution_history("candidate")
    await store.close()

@pytest.mark.asyncio
async def test_delete_task_references_retains_skill_versions(tmp_path: Path) -> None:
    store = SQLiteSkillStore(tmp_path / "app.db"); await store.init()
    path = make(tmp_path / "s" / "SKILL.md", "keep", "body")
    record = parse_skill_file(path); await store.register(record, scope="plan")
    await store.record_selection(record.skill_id)
    await store.record_outcome(record.skill_id, "task-delete", True, True)
    await store.delete_task_references("task-delete")
    assert await store.get(record.skill_id)
    metrics = await store.get_metrics(record.skill_id)
    assert metrics and metrics.selections == 1
    await store.close()

@pytest.mark.asyncio
async def test_cycle_runner_ratchets_degraded_active_and_manifest(tmp_path: Path) -> None:
    store = SQLiteSkillStore(tmp_path / "app.db"); await store.init()
    parent_path = make(tmp_path / "learned" / "skills" / "parent" / "SKILL.md", "parent", "parent")
    parent = parse_skill_file(parent_path); await store.register(parent, scope="search")
    candidate_path = make(tmp_path / "learned" / "skills" / "parent__v1_bad" / "SKILL.md", "parent", "candidate")
    candidate = SkillRecord("parent__v1_bad", "parent", str(candidate_path), "hash",
                            True, SkillLineage((parent.skill_id,), 1, "FIXED", "hash", "test"), "desc", ())
    await store.create_version(parent.skill_id, candidate, "FIXED")
    for index in range(5):
        await store.record_selection(candidate.skill_id)
        await store.record_outcome(candidate.skill_id, f"ratchet-{index}", False, False)
    files = SkillFiles(tmp_path / "learned", store); await files.update_manifest()
    class Manager:
        async def run_cycle(self): return []
    runner = EvolutionCycleRunner(Manager(), GitRatchet(), store, files)
    assert await runner.run_cycle() == []
    active = await store.get_active("parent")
    assert active and active.skill_id == parent.skill_id
    manifest = (tmp_path / "learned" / "package.json").read_text()
    assert "skills/parent/SKILL.md" in manifest and "parent__v1_bad" not in manifest
    await store.close()
