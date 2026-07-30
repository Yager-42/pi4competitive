from __future__ import annotations

from pathlib import Path

import pytest

from competitive_app.adapter.out.persistence.learned_skill_store import SQLiteSkillStore
from competitive_app.application.evolution.cycle_runner import EvolutionCycleRunner
from competitive_app.application.evolution.evolution_manager import EvolutionManager
from competitive_app.application.evolution.gates.git_ratchet import GitRatchet
from competitive_app.application.evolution.gates.score_delta_gate import ScoreDeltaGate
from competitive_app.application.evolution.mutators.llm_mutator import LLMMutator
from competitive_app.application.evolution.skill_files import SkillFiles
from competitive_app.application.evolution.triggers.metric_monitor import MetricMonitorTrigger
from competitive_app.application.evolution.parser import parse_skill_file
from competitive_app.domain.evolution.evolution_types import EvalResult


def make_skill(root: Path) -> Path:
    path = root / "skills" / "query" / "SKILL.md"; path.parent.mkdir(parents=True)
    path.write_text("---\nname: query\ndescription: query skill\nallowed-tools: [web_search]\n---\n\nMUST cite sources https://old\n", encoding="utf-8")
    return path


class LLM:
    async def complete_simple(self, prompt: str) -> str:
        return "MUST cite sources https://new\nUse official pages.\n"

class Focuser:
    async def focus(self, ctx, store): return ctx

class Bridge:
    async def evaluate(self, ctx): return EvalResult(1.0, evidence=())

@pytest.mark.asyncio
async def test_faux_fix_cycle_accepts_candidate_then_ratchets(tmp_path: Path) -> None:
    root = tmp_path / "learned"; db = SQLiteSkillStore(tmp_path / "app.db"); await db.init()
    baseline = parse_skill_file(make_skill(root)); await db.register(baseline, scope="search")
    for _ in range(10):
        await db.record_selection(baseline.skill_id); await db.record_outcome(baseline.skill_id, "t", False, False)
    trigger = MetricMonitorTrigger()
    candidate_path = root / "placeholder" / "SKILL.md"
    manager = EvolutionManager(
        db, [trigger], Focuser(), LLMMutator(root, llm=LLM()), Bridge(), ScoreDeltaGate(), llm=LLM(),
        skill_files=SkillFiles(root, db),
    )
    records = await EvolutionCycleRunner(manager).run_cycle()
    assert records and records[0].gate_decision == "accept"
    active = await db.get_active("query")
    assert active and active.skill_id != baseline.skill_id
    await db.close()
