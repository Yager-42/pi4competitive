from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from competitive_app.application.workflow.coverage_engine import CoverageEngine
from competitive_app.application.workflow.extraction import EvidenceIntake
from competitive_app.application.evolution.parser import parse_skill_file
from competitive_app.application.evolution.stage_skill_composer import StageSkillComposer


def skill(tmp_path: Path, name: str, marker: str):
    path = tmp_path / name / "SKILL.md"
    path.parent.mkdir()
    path.write_text(f"---\nname: {name}\ndescription: {name}\n---\n\n{marker}\n", encoding="utf-8")
    return parse_skill_file(path)


class Harness:
    def __init__(self):
        self.agent = SimpleNamespace(state=SimpleNamespace(systemPrompt="", messages=[], model={"id": "faux"}))
        self.seen = []
    async def prompt(self, prompt):
        self.seen.append((self.agent.state.systemPrompt, prompt))


class Models:
    def __init__(self):
        self.prompt = ""
    async def completeSimple(self, model, context):
        self.prompt = context["messages"][0]["content"]
        return {"content": "[]", "usage": {}}


@pytest.mark.asyncio
async def test_search_and_extraction_receive_only_their_scope(tmp_path: Path) -> None:
    search = skill(tmp_path, "search-skill", "SEARCH_MARKER")
    extraction = skill(tmp_path, "extract-skill", "EXTRACT_MARKER")
    harness = Harness()
    engine = CoverageEngine(
        socm_store=None, session_id="s", harness=harness, all_tools=[], store=None, task_id="t",
        abort_signal=__import__("asyncio").Event(), subagent_factory=object(),
        search_skills=[search], extraction_skills=[extraction], skill_composer=StageSkillComposer(),
    )
    await engine._run_subagent_prompt(harness, harness.agent, SimpleNamespace(intent="research"), {
        "entity_id": "x", "target_cells": ["x.a"], "question": "fill x.a"
    })
    assert "SEARCH_MARKER" in harness.agent.state.systemPrompt
    assert "EXTRACT_MARKER" not in harness.agent.state.systemPrompt
    models = Models()
    intake = EvidenceIntake(socm_store=None, session_id="s", models=models, judge_model={"id": "faux"}, extraction_skills=[extraction])
    await intake._call_judge("x", ["a"], "page")
    assert "EXTRACT_MARKER" in models.prompt
    assert "SEARCH_MARKER" not in models.prompt
