"""Fixtures for packages/agent tests."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def repo_root() -> Path:
    return ROOT


@pytest.fixture
def sessions_dir(tmp_path: Path) -> Path:
    """Isolated sessions root for tests (mirrors production data/sessions layout)."""
    d = tmp_path / "data" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def default_sessions_hint() -> str:
    """Contract D25 default relative path (not OS temp as sole SoT)."""
    return "data/sessions"
