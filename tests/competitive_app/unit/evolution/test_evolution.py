from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from competitive_app.adapter.out.persistence.learned_skill_store import SQLiteSkillStore
from competitive_app.application.evolution.evolution_manager import EvolutionManager
from competitive_app.application.evolution.focus.ive_focuser import IVEFocuser
from competitive_app.application.evolution.gates.git_ratchet import GitRatchet
from competitive_app.application.evolution.gates.score_delta_gate import ScoreDeltaGate
from competitive_app.application.evolution.mutators.llm_mutator import LLMMutator
from competitive_app.application.evolution.post_task_observer import PostTaskObserver
from competitive_app.application.evolution.triggers.metric_monitor import MetricMonitorTrigger
from competitive_app.application.evolution.skill_files import SkillFiles
from competitive_app.adapter.out.persistence.workflow_skill_store import WorkflowSkillStore
from competitive_app.application.evolution.parser import parse_skill_file
from competitive_app.domain.evolution.evolution_types import EvalResult, EvolutionContext
from competitive_app.domain.evolution.skill_types import SkillLineage, SkillRecord


def write_skill(root: Path, name: str, body: str = "MUST cite sources https://x") -> Path:
    path = root / name / "SKILL.md"; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: desc\nallowed-tools: [web_search]\n---\n\n{body}\n", encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_metric_monitor_thresholds_and_ratchet(tmp_path: Path) -> None:
    store = SQLiteSkillStore(tmp_path / "app.db"); await store.init()
    parent = parse_skill_file(write_skill(tmp_path, "s")); await store.register(parent, scope="search")
    for _ in range(10):
        await store.record_selection(parent.skill_id); await store.record_outcome(parent.skill_id, "t", False, False)
    contexts = await MetricMonitorTrigger().should_trigger(store)
    assert contexts and contexts[0].evolution_type == "FIX"
    # A single-version skill cannot roll back; adding a candidate verifies parent target.
    candidate = SkillRecord("s__v1_abcd1234", "s", str(write_skill(tmp_path, "candidate", "new")), "x", False,
                            SkillLineage((parent.skill_id,), 1, "FIXED", "x", "test"), "desc", ("web_search",))
    await store.create_version(parent.skill_id, candidate, "FIXED")
    for _ in range(5):
        await store.record_selection(candidate.skill_id)
        await store.record_outcome(candidate.skill_id, "t2", False, False)
    current = await store.get_active("s")
    rolled = await GitRatchet().check_and_rollback(store, current)
    assert rolled == parent.skill_id
    await store.close()


class LLM:
    async def complete_simple(self, prompt: str) -> str:
        if "SKILL.md body" in prompt:
            return "MUST cite sources https://new\nUse official sources."
        return "---\nname: captured\ndescription: captured desc\n---\n\nMUST use this pattern.\n"


@pytest.mark.asyncio
async def test_mutator_and_gate(tmp_path: Path) -> None:
    path = write_skill(tmp_path, "fixme")
    baseline = parse_skill_file(path)
    mutator = LLMMutator(tmp_path / "learned", llm=LLM())
    candidate, diff = await mutator.mutate(EvolutionContext("METRIC", "FIX", baseline, fix_direction="cite"))
    assert candidate.name == baseline.name and candidate.allowed_tools == baseline.allowed_tools and diff
    assert (Path(candidate.path).parent / ".skill_id").exists()
    assert ScoreDeltaGate().decide(candidate, None, EvalResult(.1)).recommendation == "accept"
    assert ScoreDeltaGate().decide(candidate, baseline, EvalResult(.1)).recommendation == "accept"


@pytest.mark.asyncio
async def test_captured_observer_requires_all_evidence(tmp_path: Path) -> None:
    obs = WorkflowSkillStore(tmp_path / "app.db"); await obs.init()
    observer = PostTaskObserver(observation_store=obs)
    assert await observer.observe(task_id="a", status="aborted", scope="plan", problem_signature="p", solution="s", transferability="t", solution_demonstrated=True) is None
    assert await observer.observe(task_id="a", status="completed", scope="plan", problem_signature="p", solution="", transferability="t", solution_demonstrated=True) is None
    context = await observer.observe(task_id="b", status="completed", scope="plan", problem_signature="p2", solution="s", transferability="t", solution_demonstrated=True, suggested_name="captured")
    assert context and context.evolution_type == "CAPTURED" and context.suggested_name == "captured"
    assert context.observation_id and await observer.mark_consumed(context.observation_id)
    remaining = await obs.list_observations(unconsumed_only=True)
    assert len(remaining) == 1 and remaining[0]["problem_signature"] == "p"
    await obs.close()

@pytest.mark.asyncio
async def test_captured_mutator_adds_required_frontmatter(tmp_path: Path) -> None:
    class BareLLM:
        async def complete_simple(self, _prompt): return "Use the demonstrated solution."
    mutator = LLMMutator(tmp_path / "learned", llm=BareLLM())
    candidate, _ = await mutator.mutate(
        EvolutionContext("CAPTURE", "CAPTURED", None, capture_pattern="worked", suggested_name="captured", scope="write")
    )
    parsed = parse_skill_file(candidate.path)
    assert parsed.name == "captured" and parsed.description and parsed.allowed_tools == ()
