from __future__ import annotations

from pathlib import Path
import asyncio
from types import SimpleNamespace

import pytest

from competitive_app.application.evolution.evolution_manager import EvolutionManager, EvolutionRecoveryError
from competitive_app.application.evolution.focus.ive_focuser import IVEFocuser
from competitive_app.application.evolution.post_task_observer import PostTaskObserver
from competitive_app.application.evolution.selector import SkillSelector
from competitive_app.application.evolution.skill_files import SkillFiles
from competitive_app.application.evolution.triggers.metric_monitor import MetricMonitorTrigger
from competitive_app.domain.evolution.evolution_types import EvalResult, EvolutionContext, FailureEvidence
from competitive_app.domain.evolution.skill_types import SkillRecord


def _record(skill_id: str, name: str | None = None, **kwargs: object) -> SkillRecord:
    values = {"path": "", "content_hash": f"hash-{skill_id}", **kwargs}
    return SkillRecord(skill_id, name or skill_id, **values)


@pytest.mark.asyncio
async def test_manager_rolls_back_projection_after_accept_failure(tmp_path: Path) -> None:
    baseline = _record("parent", "demo")
    candidate_path = tmp_path / "skills" / "demo__v1" / "SKILL.md"
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text("candidate", encoding="utf-8")
    candidate = _record("demo__v1", "demo", path=str(candidate_path))

    class Store:
        def __init__(self) -> None:
            self.rolled_back: list[str] = []

        async def get_metrics(self, _skill_id: str):
            return None

        async def create_version(self, *_args):
            return candidate.skill_id

        async def rollback(self, skill_id: str) -> None:
            self.rolled_back.append(skill_id)

        async def get_active(self, _name: str):
            # The store must be able to verify the restored active pointer;
            # without it the manager fails closed (EvolutionRecoveryError).
            return baseline

    class Focuser:
        async def focus(self, context, _store):
            return context

    class Mutator:
        async def mutate(self, _context, _llm):
            return candidate, "diff"

    class Bridge:
        async def evaluate(self, _ctx):
            return EvalResult(1.0)

    class Gate:
        def decide(self, *_args):
            return SimpleNamespace(recommendation="accept")

    class Files:
        def __init__(self) -> None:
            self.rejected = False
            self.manifest_updates = 0

        async def accept_candidate(self, *_args, **_kwargs):
            self.rejected = False
            raise OSError("manifest write failed after projection")

        async def reject_candidate(self, _candidate):
            self.rejected = True

        async def update_manifest(self):
            self.manifest_updates += 1

    store = Store()
    files = Files()
    manager = EvolutionManager(store, [], Focuser(), Mutator(), Bridge(), Gate(), skill_files=files)
    context = EvolutionContext("METRIC", "FIX", baseline, scope="search")
    assert await manager.run_context(context) is None
    assert store.rolled_back == [baseline.skill_id]
    assert files.rejected and files.manifest_updates == 1

@pytest.mark.asyncio
async def test_manager_surfaces_acceptance_and_rollback_failures(tmp_path: Path) -> None:
    baseline = _record("parent", "demo")
    candidate_path = tmp_path / "skills" / "demo__v1" / "SKILL.md"
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text("candidate", encoding="utf-8")
    candidate = _record("demo__v1", "demo", path=str(candidate_path))
    acceptance_error = OSError("projection failed")
    rollback_error = RuntimeError("rollback unavailable")

    class Store:
        async def get_metrics(self, _skill_id: str):
            return None

        async def create_version(self, *_args):
            return candidate.skill_id

        async def rollback(self, _skill_id: str) -> None:
            raise rollback_error

        async def get_active(self, _name: str):
            return candidate

    class Focuser:
        async def focus(self, context, _store):
            return context

    class Mutator:
        async def mutate(self, _context, _llm):
            return candidate, "diff"

    class Bridge:
        async def evaluate(self, _ctx):
            return EvalResult(1.0)

    class Gate:
        def decide(self, *_args):
            return SimpleNamespace(recommendation="accept")

    class Files:
        async def accept_candidate(self, *_args, **_kwargs):
            raise acceptance_error

        async def reject_candidate(self, _candidate):
            raise AssertionError("candidate must remain for recovery")

        async def update_manifest(self):
            raise AssertionError("manifest must not publish an uncertain pointer")

    store = Store()
    manager = EvolutionManager(store, [], Focuser(), Mutator(), Bridge(), Gate(), skill_files=Files())
    with pytest.raises(EvolutionRecoveryError) as raised:
        await manager.run_context(EvolutionContext("METRIC", "FIX", baseline, scope="search"))
    assert raised.value.original_error is acceptance_error
    assert raised.value.__cause__ is acceptance_error
    assert raised.value.recovery_errors == (rollback_error,)
    assert (await store.get_active("demo")).skill_id == candidate.skill_id
    assert candidate_path.is_file()


@pytest.mark.asyncio
async def test_focuser_does_not_count_provider_or_shape_errors() -> None:
    class BrokenLLM:
        async def complete_json(self, _prompt):
            return ["unsupported"]

    evidence = FailureEvidence(1, "tool", "IMPLEMENTATION", "bad result")
    context = EvolutionContext("ANALYSIS", "FIX", None, failure_evidence=(evidence,), suggested_name="skill")
    focuser = IVEFocuser(BrokenLLM(), impl_fail_threshold=1)
    result = await focuser.focus(context, None)
    assert result.failure_evidence == (evidence,)
    assert focuser._impl_fail_counts == {}


@pytest.mark.asyncio
async def test_observer_deduplicates_punctuation_variants() -> None:
    class Observations:
        def __init__(self) -> None:
            self.items: list[dict[str, str]] = []

        async def add_observation(self, **kwargs):
            self.items.append(kwargs)

        async def list_observations(self, **_kwargs):
            return self.items

    observer = PostTaskObserver(observation_store=Observations())
    first = await observer.observe(
        task_id="one", status="completed", scope="write",
        problem_signature="write.refine.foo: fix", solution="done",
        transferability="general", solution_demonstrated=True,
    )
    second = await observer.observe(
        task_id="two", status="completed", scope="write",
        problem_signature="write refine foo - fix", solution="done",
        transferability="general", solution_demonstrated=True,
    )
    assert first is not None
    assert second is None


@pytest.mark.asyncio
async def test_selector_caps_and_retains_forced_records() -> None:
    records = [_record(f"s{i}", f"skill-{i}") for i in range(4)]

    class Store:
        async def get_active(self, name, scope=None):
            del scope
            return next((r for r in records if r.name == name), None)

        async def list_active(self, scope=None):
            del scope
            return records

    selected = await SkillSelector(Store(), max_skills=2).select_for_scope(
        "task", "plan", overrides=["skill-0", "skill-1", "skill-2"]
    )
    assert [record.name for record in selected] == ["skill-0", "skill-1"]


@pytest.mark.asyncio
async def test_selector_legacy_unscoped_fallback_fails_closed() -> None:
    class Store:
        async def list_active(self):
            return [_record("unscoped")]

        async def get_active(self, _name):
            return None

    assert await SkillSelector(Store())._store_list_active("search") == []


@pytest.mark.asyncio
async def test_skill_projection_commits_dependencies_before_manifest(tmp_path: Path) -> None:
    path = tmp_path / "skills" / "candidate" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("candidate", encoding="utf-8")
    candidate = _record("candidate", path=str(path))
    events: list[str] = []

    class Store:
        async def list_active(self):
            return [candidate]

    class Scope:
        async def get_scope(self, *_args):
            return None

        async def clear_scope(self, *_args):
            events.append("clear")

        async def set_scope(self, *_args):
            events.append("scope")

    files = SkillFiles(tmp_path, Store(), Scope())

    async def write_manifest():
        events.append("manifest")
        assert (path.parent / ".skill_id").read_text(encoding="utf-8") == candidate.skill_id

    files._write_manifest_locked = write_manifest
    await files.accept_candidate(candidate, scope="write")
    assert events == ["scope", "manifest"]


@pytest.mark.asyncio
async def test_skill_projection_manifest_failure_has_no_marker_or_scope(tmp_path: Path) -> None:
    path = tmp_path / "skills" / "candidate" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("candidate", encoding="utf-8")
    candidate = _record("candidate", path=str(path))

    class Store:
        async def list_active(self):
            return [candidate]

    class Scope:
        def __init__(self) -> None:
            self.sets = 0
            self.clears = 0

        async def get_scope(self, *_args):
            return None

        async def set_scope(self, *_args):
            self.sets += 1

        async def clear_scope(self, *_args):
            self.clears += 1

    files = SkillFiles(tmp_path, Store(), Scope())

    async def fail_manifest():
        raise OSError("fsync failed")

    files._write_manifest_locked = fail_manifest
    with pytest.raises(OSError):
        await files.accept_candidate(candidate, scope="write")
    assert not (path.parent / ".skill_id").exists()
    # A failed manifest publication must roll the scope row back as well.
    assert files._scope_store.sets == 1
    assert files._scope_store.clears == 1


@pytest.mark.asyncio
async def test_skill_projection_snapshot_failure_does_not_clear_existing_scope(
    tmp_path: Path,
) -> None:
    path = tmp_path / "skills" / "candidate" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("candidate", encoding="utf-8")
    candidate = _record("candidate", path=str(path))

    class Store:
        async def list_active(self):
            return [candidate]

    class Scope:
        sets = 0
        clears = 0

        async def get_scope(self, *_args):
            raise OSError("scope store unavailable")

        async def set_scope(self, *_args):
            self.sets += 1

        async def clear_scope(self, *_args):
            self.clears += 1

    scope = Scope()
    files = SkillFiles(tmp_path, Store(), scope)
    with pytest.raises(OSError, match="scope store unavailable"):
        await files.accept_candidate(candidate, scope="write")
    assert scope.sets == 0
    assert scope.clears == 0
    assert not (path.parent / ".skill_id").exists()


@pytest.mark.asyncio
async def test_skill_projection_requires_rollback_capability_before_mutation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "skills" / "candidate" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("candidate", encoding="utf-8")
    candidate = _record("candidate", path=str(path))

    class Store:
        async def list_active(self):
            return [candidate]

    class IncompleteScope:
        async def get_scope(self, *_args):
            return None

        async def set_scope(self, *_args):
            return None

    with pytest.raises(TypeError, match="clear_scope"):
        await SkillFiles(tmp_path, Store(), IncompleteScope()).accept_candidate(
            candidate, scope="write"
        )
    assert not (path.parent / ".skill_id").exists()


@pytest.mark.asyncio
async def test_skill_projection_cancellation_rolls_back_committed_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "skills" / "candidate" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("candidate", encoding="utf-8")
    candidate = _record("candidate", path=str(path))

    class Store:
        async def list_active(self):
            return [candidate]

    class Scope:
        sets = 0
        clears = 0

        async def get_scope(self, *_args):
            return None

        async def set_scope(self, *_args):
            self.sets += 1

        async def clear_scope(self, *_args):
            self.clears += 1

    files = SkillFiles(tmp_path, Store(), Scope())

    async def cancelled_manifest():
        raise asyncio.CancelledError()

    monkeypatch.setattr(files, "_write_manifest_locked", cancelled_manifest)
    with pytest.raises(asyncio.CancelledError):
        await files.accept_candidate(candidate, scope="write")
    assert not (path.parent / ".skill_id").exists()
    assert files._scope_store.sets == 1
    assert files._scope_store.clears == 1


def test_metric_monitor_uses_configured_threshold() -> None:
    record = _record("s", total_selections=10, total_applied=5, total_completions=4)
    assert MetricMonitorTrigger(threshold=0.3)._diagnose_skill_health(record)[0] is None
    assert MetricMonitorTrigger(threshold=0.5)._diagnose_skill_health(record)[0] == "DERIVED"
