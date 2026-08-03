"""Workflow Skill live closeout smoke (L1/L2).

These tests are env-gated and use isolated temporary roots/databases; they never
write the production promotion corpus and are not a quality benchmark.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient
import pytest

pytestmark = [pytest.mark.live, pytest.mark.asyncio]

_TASK = {
    "research_brief": {
        "target": {"name": "CompetitorLens", "category": "research tool"},
        "goal": "Compare one product with one competitor on pricing and one feature",
        "competitors": ["Alternative"],
        "dimensions": ["pricing", "features"],
    },
    "metadata": {"trace": "workflow-skill-live"},
}


def _write_skill(root: Path, name: str, scope: str, body: str) -> Path:
    path = root / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {name} live workflow guidance\nscope: {scope}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return path


async def _client(state):
    from competitive_app.adapter.in_.fastapi.app import create_app
    app = create_app()
    app.state.application = state  # type: ignore[attr-defined]
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _wait_terminal(client: AsyncClient, task_id: str, timeout: float = 420.0) -> str:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/api/v2/tasks/{task_id}")
        status = response.json().get("status")
        if status in {"completed", "failed", "aborted"}:
            return status
        await asyncio.sleep(1)
    return "timeout"


async def test_live_workflow_skill_search_injection_and_outcome(tmp_path: Path, live_env, monkeypatch: pytest.MonkeyPatch) -> None:
    """L1: real provider completes a task with a selected search Skill."""
    root = tmp_path / "learned"
    _write_skill(root, "live-search", "search", """Search official sources first.
For every claim, retain the source URL and a short supporting excerpt.
Do not invent values; mark unknown cells explicitly.""")
    _write_skill(root, "live-plan", "plan", "Define one entity and concrete attributes before searching.")
    _write_skill(root, "live-extraction", "extraction", "Extract only claims supported by the fetched source and preserve URLs.")
    _write_skill(root, "live-write", "write", "Write concise markdown with citation-backed claims and explicit unknowns.")
    monkeypatch.setenv("SESSIONS_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("APP_DB", str(tmp_path / "app.db"))
    monkeypatch.setenv("SESSIONS_CWD", "live-workflow-skill")
    monkeypatch.setenv("WORKFLOW_SKILL_ENABLED", "1")
    monkeypatch.setenv("WORKFLOW_SKILL_EVAL_ENABLED", "1")
    monkeypatch.setenv("WORKFLOW_SKILL_ROOT", str(root))
    monkeypatch.setenv("CAPABILITY_PACKAGES_ENABLED", "echo_example,search_tavily,search_anysearch,search_grok")
    from competitive_app.wiring import build_application_state, load_config_from_env
    state = await build_application_state(load_config_from_env())
    try:
        async with await _client(state) as client:
            created = await client.post("/api/v2/tasks", json=_TASK)
            assert created.status_code == 202, created.text
            task_id = created.json()["task_id"]
            status = await _wait_terminal(client, task_id)
            assert status == "completed"
            report = await client.get(f"/api/v2/tasks/{task_id}/report")
            assert report.status_code == 200 and report.json()["report"]
        expected = {"plan": "live-plan", "search": "live-search", "extraction": "live-extraction", "write": "live-write"}
        for scope, name in expected.items():
            scope_ids = await state.workflow_skill_store.get_bindings(task_id, scope)
            assert len(scope_ids) <= 3
            scope_records = [await state.skill_store.get(skill_id) for skill_id in scope_ids]
            assert any(record is not None and record.name == name for record in scope_records)
        bound = await state.workflow_skill_store.get_bindings(task_id, "search")
        bound_record = [await state.skill_store.get(skill_id) for skill_id in bound]
        selected = next((record for record in bound_record if record is not None and record.name == "live-search"), None)
        assert selected is not None
        metrics = await state.skill_store.get_metrics(selected.skill_id)
        assert metrics and metrics.selections >= 1
        judgments = []
        deadline = asyncio.get_running_loop().time() + 180
        while asyncio.get_running_loop().time() < deadline:
            judgments = await state.skill_store.get_judgments(selected.skill_id)
            if judgments: break
            await asyncio.sleep(1)
        assert judgments, "completed live task must persist a Skill judgment"
    finally:
        await state.shutdown()


async def test_live_workflow_skill_fix_cycle_parses_and_gates(tmp_path: Path, live_env, monkeypatch: pytest.MonkeyPatch) -> None:
    """L2: real provider produces one FIX candidate; gate result is observable."""
    root = tmp_path / "learned"
    _write_skill(root, "live-fix", "search", "Always inspect official sources before summarizing.")
    monkeypatch.setenv("SESSIONS_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("APP_DB", str(tmp_path / "app.db"))
    monkeypatch.setenv("SESSIONS_CWD", "live-workflow-evolution")
    monkeypatch.setenv("WORKFLOW_SKILL_ENABLED", "1")
    monkeypatch.setenv("WORKFLOW_SKILL_EVOLVE_ENABLED", "1")
    monkeypatch.setenv("WORKFLOW_SKILL_EVAL_ENABLED", "1")
    monkeypatch.setenv("WORKFLOW_SKILL_ROOT", str(root))
    from competitive_app.wiring import build_application_state, load_config_from_env
    from competitive_app.domain.evolution.evolution_types import EvolutionContext
    state = await build_application_state(load_config_from_env())
    captured: list[object] = []
    try:
        baseline = await state.skill_store.get_active("live-fix")
        assert baseline is not None
        for index in range(10):
            await state.skill_store.record_selection(baseline.skill_id)
            await state.skill_store.record_outcome(baseline.skill_id, f"seed-{index}", False, False)
        original = state.evolution_manager._mutator
        class CapturingMutator:
            async def mutate(self, ctx, llm=None):
                candidate, diff = await original.mutate(ctx, llm)
                from competitive_app.application.evolution.parser import parse_skill_file
                parse_skill_file(candidate.path)
                captured.append(candidate)
                return candidate, diff
        state.evolution_manager._mutator = CapturingMutator()
        result = await state.evolution_manager.run_context(
            EvolutionContext("METRIC", "FIX", baseline, fix_direction="improve source discipline", scope="search")
        )
        assert captured and result and result.gate_decision in {"accept", "reject"}
        assert result.eval_score >= 0.0
        history = await state.skill_store.get_evolution_history("live-fix")
        assert history and history[0]["candidate_id"] == result.candidate_id
    finally:
        await state.shutdown()

async def test_live_workflow_skill_captured_refine_chain(tmp_path: Path, live_env, monkeypatch: pytest.MonkeyPatch) -> None:
    """L3: real task feedback + refine drives automatic CAPTURED evolution."""
    root = tmp_path / "learned"
    _write_skill(root, "live-plan", "plan", "Plan a typed coverage schema before searching.")
    _write_skill(root, "live-search", "search", "Search official sources and retain source URLs.")
    _write_skill(root, "live-extraction", "extraction", "Extract only source-supported claims.")
    _write_skill(root, "live-write", "write", "Write citation-grounded markdown with explicit unknowns.")
    monkeypatch.setenv("SESSIONS_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("APP_DB", str(tmp_path / "app.db"))
    monkeypatch.setenv("SESSIONS_CWD", "live-workflow-captured")
    monkeypatch.setenv("WORKFLOW_SKILL_ENABLED", "1")
    monkeypatch.setenv("WORKFLOW_SKILL_EVOLVE_ENABLED", "1")
    monkeypatch.setenv("WORKFLOW_SKILL_EVAL_ENABLED", "1")
    monkeypatch.setenv("WORKFLOW_SKILL_ROOT", str(root))
    monkeypatch.setenv("CAPABILITY_PACKAGES_ENABLED", "echo_example,search_tavily,search_anysearch,search_grok")
    from competitive_app.application.evolution.parser import parse_skill_file
    from competitive_app.wiring import build_application_state, load_config_from_env
    state = await build_application_state(load_config_from_env())
    captured: list[object] = []
    try:
        original = state.evolution_manager._mutator
        class CapturingMutator:
            async def mutate(self, ctx, llm=None):
                candidate, diff = await original.mutate(ctx, llm)
                parse_skill_file(candidate.path)
                captured.append(candidate)
                return candidate, diff
        state.evolution_manager._mutator = CapturingMutator()
        async with await _client(state) as client:
            created = await client.post("/api/v2/tasks", json=_TASK)
            assert created.status_code == 202, created.text
            task_id = created.json()["task_id"]
            assert await _wait_terminal(client, task_id) == "completed"
            full = await client.get(f"/api/v2/reports/{task_id}")
            assert full.status_code == 200 and full.json().get("sections")
            section_id = str(full.json()["sections"][0]["id"])
            feedback = await client.post(
                f"/api/v2/reports/{task_id}/feedback",
                json={"edited_blocks": 1, "total_blocks": 1, "data": {"reason": "citation gap"}},
            )
            assert feedback.status_code == 200
            refined = await client.post(
                f"/api/v2/reports/{task_id}/refine",
                json={"section_id": section_id, "annotations": ["Add source-backed pricing detail"]},
            )
            assert refined.status_code == 200 and refined.json().get("ok") is True
        assert captured, "refine must invoke the real CAPTURED mutator"
        import aiosqlite
        db = await aiosqlite.connect(str(tmp_path / "app.db"))
        try:
            async with db.execute("SELECT evolution_type,gate_decision,eval_score,created_version_id FROM skill_evolutions ORDER BY timestamp DESC LIMIT 1") as cursor:
                row = await cursor.fetchone()
        finally:
            await db.close()
        assert row and row[0] == "CAPTURED" and row[1] in {"accept", "reject"} and row[2] > 0
    finally:
        await state.shutdown()

async def test_live_workflow_skill_fix_cycle_runs_after_task_completion(tmp_path: Path, live_env, monkeypatch: pytest.MonkeyPatch) -> None:
    """L4: a degraded active Skill triggers real FIX evolution after a task."""
    root = tmp_path / "learned"
    _write_skill(root, "live-fix", "search", "Search official sources and retain citations.")
    monkeypatch.setenv("SESSIONS_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("APP_DB", str(tmp_path / "app.db"))
    monkeypatch.setenv("SESSIONS_CWD", "live-workflow-fix")
    monkeypatch.setenv("WORKFLOW_SKILL_ENABLED", "1")
    monkeypatch.setenv("WORKFLOW_SKILL_EVOLVE_ENABLED", "1")
    monkeypatch.setenv("WORKFLOW_SKILL_EVAL_ENABLED", "1")
    monkeypatch.setenv("WORKFLOW_SKILL_ROOT", str(root))
    monkeypatch.setenv("CAPABILITY_PACKAGES_ENABLED", "echo_example,search_tavily,search_anysearch,search_grok")
    from competitive_app.application.evolution.parser import parse_skill_file
    from competitive_app.wiring import build_application_state, load_config_from_env
    state = await build_application_state(load_config_from_env())
    captured: list[object] = []
    try:
        baseline = await state.skill_store.get_active("live-fix")
        assert baseline is not None
        for index in range(10):
            await state.skill_store.record_selection(baseline.skill_id)
            await state.skill_store.record_outcome(baseline.skill_id, f"seed-{index}", False, False)
        original = state.evolution_manager._mutator
        class CapturingMutator:
            async def mutate(self, ctx, llm=None):
                candidate, diff = await original.mutate(ctx, llm)
                parse_skill_file(candidate.path)
                captured.append(candidate)
                return candidate, diff
        state.evolution_manager._mutator = CapturingMutator()
        async with await _client(state) as client:
            created = await client.post("/api/v2/tasks", json=_TASK)
            assert created.status_code == 202, created.text
            task_id = created.json()["task_id"]
            assert await _wait_terminal(client, task_id) == "completed"
        import aiosqlite
        deadline = asyncio.get_running_loop().time() + 180
        row = None
        while asyncio.get_running_loop().time() < deadline:
            db = await aiosqlite.connect(str(tmp_path / "app.db"))
            try:
                async with db.execute("SELECT evolution_type,gate_decision,eval_score FROM skill_evolutions ORDER BY timestamp DESC LIMIT 1") as cursor:
                    row = await cursor.fetchone()
            finally:
                await db.close()
            if row is not None:
                break
            await asyncio.sleep(1)
        assert captured and row and row[0] == "FIX" and row[1] in {"accept", "reject"} and row[2] >= 0
        from competitive_app.domain.evolution.skill_types import SkillLineage, SkillRecord
        import hashlib
        parent = await state.skill_store.get_active("live-fix")
        assert parent is not None
        candidate_id = f"{parent.name}__v{parent.lineage.generation + 1}_live1234"
        candidate_path = root / "skills" / candidate_id / "SKILL.md"
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        content = Path(parent.path).read_text(encoding="utf-8")
        candidate_path.write_text(content, encoding="utf-8")
        digest = hashlib.sha256(content.encode()).hexdigest()[:16]
        candidate = SkillRecord(
            candidate_id, parent.name, str(candidate_path), digest, False,
            SkillLineage((parent.skill_id,), parent.lineage.generation + 1, "FIXED", digest, "live-test"),
            parent.description, parent.allowed_tools,
        )
        await state.skill_store.create_version(parent.skill_id, candidate, "FIXED")
        await state.workflow_skill_store.set_scope(candidate_id, "search", str(candidate_path))
        for index in range(5):
            await state.skill_store.record_selection(candidate_id)
            await state.skill_store.record_outcome(candidate_id, f"rollback-{index}", False, False)
        await state.task_service._evolution_cycle_runner.run_cycle()
        rolled = await state.skill_store.get_active("live-fix")
        assert rolled and rolled.skill_id == parent.skill_id
        manifest = (root / "package.json").read_text(encoding="utf-8")
        assert candidate_id not in manifest
    finally:
        await state.shutdown()
