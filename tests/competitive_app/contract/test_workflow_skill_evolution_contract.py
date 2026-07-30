from __future__ import annotations

import ast
import json
from pathlib import Path

from competitive_app.application.evolution.config import SkillConfig, SkillEvalConfig

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "competitive_app" / "src" / "competitive_app"


def test_learned_manifest_starts_active_only() -> None:
    data = json.loads((ROOT / "capability_packages/learned_skills/package.json").read_text())
    assert data["pi"]["skills"] == []


def test_four_scopes_and_defaults() -> None:
    from competitive_app.domain.evolution.workflow_scope import SCOPES
    assert SCOPES == ("plan", "search", "extraction", "write")
    assert SkillConfig().enabled is False
    assert SkillConfig().evolve_enabled is False
    assert SkillEvalConfig().enabled is False


def test_domain_evolution_has_no_io_imports() -> None:
    forbidden = {"fastapi", "aiosqlite", "earendil_works", "pathlib", "os", "sqlite3"}
    offenders = []
    for path in (APP / "domain/evolution").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders.extend((str(path), alias.name.split(".")[0]) for alias in node.names if alias.name.split(".")[0] in forbidden)
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in forbidden:
                offenders.append((str(path), node.module.split(".")[0]))
    assert not offenders


def test_no_manual_capture_manager_api() -> None:
    source = (APP / "application/evolution/evolution_manager.py").read_text()
    assert "def capture_skill" not in source
    assert "def evolve_skill" not in source


def test_plan_target_modules_exist() -> None:
    expected = [
        "application/evolution/parser.py", "application/evolution/injector.py",
        "application/evolution/selector.py", "application/evolution/stage_skill_composer.py",
        "application/evolution/evolution_manager.py", "application/evolution/cycle_runner.py",
        "application/evolution/eval/registry.py", "application/evolution/eval/programmatic_bridge.py",
    ]
    assert all((APP / p).is_file() for p in expected)
