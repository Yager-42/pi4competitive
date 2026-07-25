"""Contract O1 — competitive_app DDD layout exists and imports."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP_SRC = ROOT / "competitive_app" / "src" / "competitive_app"


def test_competitive_app_path_exists() -> None:
    assert APP_SRC.is_dir()


def test_ddd_layers_exist() -> None:
    for layer in ("domain", "application", "adapter", "wiring.py"):
        assert (APP_SRC / layer).exists(), f"missing layer: {layer}"


def test_adapter_sublayers_exist() -> None:
    assert (APP_SRC / "adapter" / "in_" / "fastapi").is_dir()
    assert (APP_SRC / "adapter" / "out" / "persistence").is_dir()


def test_import_competitive_app() -> None:
    import competitive_app

    assert competitive_app.__name__ == "competitive_app"


def test_pyproject_declares_pi_agent_dep() -> None:
    pyproject = (ROOT / "competitive_app" / "pyproject.toml").read_text(encoding="utf-8")
    assert "earendil-works-pi-agent" in pyproject
    assert "fastapi" in pyproject
    assert "aiosqlite" in pyproject
