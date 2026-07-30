from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from competitive_app.application.evolution.config import load_skill_config
from competitive_app.application.evolution.parser import parse_skill_file
from competitive_app.adapter.out.persistence.learned_skill_store import SQLiteSkillStore
from competitive_app.domain.evolution.skill_types import SkillLineage, SkillRecord


def _skill(path: Path, name: str = "search-help") -> str:
    text = f"---\nname: {name}\ndescription: Useful guidance\nallowed-tools: [web_search]\nenabled: true\n---\n\nMUST cite sources.\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def test_parser_preserves_id_hash_and_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    text = _skill(path)
    record = parse_skill_file(path)
    assert record.skill_id.startswith("search-help__imp_")
    assert (path.parent / ".skill_id").read_text() == record.skill_id
    assert record.content_hash == hashlib.sha256(text.encode()).hexdigest()[:16]
    assert record.allowed_tools == ("web_search",)
    assert parse_skill_file(path).skill_id == record.skill_id


@pytest.mark.asyncio
async def test_store_dag_metrics_and_rollback(tmp_path: Path) -> None:
    db = SQLiteSkillStore(tmp_path / "app.db")
    await db.init()
    source = tmp_path / "source" / "SKILL.md"
    text = _skill(source, "query-plan")
    parent = parse_skill_file(source)
    await db.register(parent, scope="plan")
    assert (await db.get_active("query-plan")).skill_id == parent.skill_id
    for _ in range(5):
        await db.record_selection(parent.skill_id)
        await db.record_outcome(parent.skill_id, "task", False, False)
    metrics = await db.get_metrics(parent.skill_id)
    assert metrics and metrics.selections == 5 and metrics.fallback_rate == 1.0
    candidate_path = tmp_path / "candidate" / "SKILL.md"
    candidate_text = _skill(candidate_path, "query-plan")
    candidate = SkillRecord(
        "query-plan__v1_abcd1234", "query-plan", str(candidate_path), hashlib.sha256(candidate_text.encode()).hexdigest()[:16],
        False, SkillLineage((parent.skill_id,), 1, "FIXED", "", "test"), parent.description, parent.allowed_tools,
    )
    await db.create_version(parent.skill_id, candidate, "FIXED")
    assert (await db.get_active("query-plan")).skill_id == candidate.skill_id
    await db.rollback(parent.skill_id)
    assert (await db.get_active("query-plan")).skill_id == parent.skill_id
    assert len(await db.get_versions("query-plan")) == 2
    await db.close()


def test_config_bad_numbers_use_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKFLOW_SKILL_MAX_INJECT", "bad")
    monkeypatch.setenv("WORKFLOW_SKILL_QUALITY_THRESHOLD", "bad")
    cfg = load_skill_config()
    assert cfg.max_inject == 3 and cfg.quality_threshold == 0.3
    assert not cfg.enabled and not cfg.evolve_enabled and not cfg.eval_config.enabled

def test_config_uses_cooldown_selections_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKFLOW_SKILL_EVOLVE_COOLDOWN_SELECTIONS", "7")
    assert load_skill_config().evolve_cooldown_turns == 7

@pytest.mark.asyncio
async def test_store_discover_honors_active_manifest(tmp_path: Path) -> None:
    import json
    root = tmp_path / "learned"
    active = Path(_skill(root / "skills" / "active" / "SKILL.md", "active"))
    _skill(root / "skills" / "candidate" / "SKILL.md", "candidate")
    (root / "package.json").write_text(json.dumps({"pi": {"skills": ["skills/active/SKILL.md"]}}), encoding="utf-8")
    store = SQLiteSkillStore(tmp_path / "app.db"); await store.init()
    records = await store.discover([root / "skills"])
    assert [record.name for record in records] == ["active"]
    assert await store.get_active("candidate") is None
    await store.close()
