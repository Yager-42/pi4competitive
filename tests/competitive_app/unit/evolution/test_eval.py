from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from competitive_app.application.evolution.eval.analyzers.contract_compiler import ContractCompiler
from competitive_app.application.evolution.eval.analyzers.response_contract_checker import ResponseContractChecker
from competitive_app.application.evolution.eval.programmatic_bridge import ProgrammaticEvalBridge
from competitive_app.application.evolution.eval.registry import EvalRegistry, RegistryEvalBridge
from competitive_app.application.evolution.eval.analyzers.task_quality_judge import TaskQualityJudge
from competitive_app.application.evolution.eval.runtime_tracker import RuntimeTracker
from competitive_app.domain.evolution.evolution_types import EvalContext
from competitive_app.domain.evolution.eval_types import SkillJudgment


def record(tmp_path: Path, text: str):
    path = tmp_path / "SKILL.md"
    path.write_text(text, encoding="utf-8")
    return SimpleNamespace(path=str(path))


@pytest.mark.asyncio
async def test_contract_checker_and_fail_closed_registry(tmp_path: Path) -> None:
    baseline = record(tmp_path, "---\nname: x\ndescription: x\n---\n\nMUST cite sources https://example.com\n")
    candidate = record(tmp_path, "---\nname: x\ndescription: x\n---\n\n")
    result = await ProgrammaticEvalBridge().evaluate(EvalContext(baseline, candidate))
    assert result.hard_failures == ("nonempty",)
    bridge = RegistryEvalBridge(EvalRegistry(None))
    closed = await bridge.evaluate(EvalContext(baseline, candidate))
    assert closed.score == 0 and closed.hard_failures == ("eval_exception",)
    assert "must_cite" in {rule.rule_id for rule in ContractCompiler().compile("cite sources")}


class Judge:
    async def complete_json(self, prompt):
        return {"task_completion": 1, "response_quality": .8, "efficiency": .6, "tool_usage": .4, "rationale": "ok"}


@pytest.mark.asyncio
async def test_quality_weights_and_runtime_trend() -> None:
    judge = TaskQualityJudge(Judge())
    score = await judge.judge_task("t", "x" * 100000, "y" * 30000)
    assert score and score.overall_score == round(.5 + .35*.8 + .05*.6 + .1*.4, 3)
    class Store:
        async def get_metrics(self, _):
            return SimpleNamespace(selections=4, applied=2, completions=1, fallbacks=0, applied_rate=.5, completion_rate=.5, effective_rate=.25, fallback_rate=0)
        async def get_judgments(self, _, __):
            return [SkillJudgment(str(i), "s", "s", "t", i < 2) for i in range(4)]
        async def get(self, _): return SimpleNamespace(name="s")
        async def list_active(self): return []
    report = await RuntimeTracker(Store()).health_report("s")
    assert report.trend in {"stable", "improving", "degrading", "insufficient_data"}

@pytest.mark.asyncio
async def test_judgment_analyzer_normalizes_skill_name_to_id() -> None:
    from competitive_app.application.evolution.eval.analyzers.skill_judgment_analyzer import SkillJudgmentAnalyzer

    class LLM:
        async def complete_json(self, _prompt):
            return {"judgments": [{"skill_id": "friendly-name", "skill_applied": True}], "suggestions": []}
    class Store:
        def __init__(self): self.saved = []
        async def save_judgment(self, judgment): self.saved.append(judgment)
        async def record_outcome(self, *args): pass
    store = Store()
    result, _ = await SkillJudgmentAnalyzer(LLM(), store).analyze_execution(
        "task", [], "summary", [{"skill_id": "stable-id", "name": "friendly-name"}]
    )
    assert [item.skill_id for item in result] == ["stable-id"]
    assert [item.skill_id for item in store.saved] == ["stable-id"]
