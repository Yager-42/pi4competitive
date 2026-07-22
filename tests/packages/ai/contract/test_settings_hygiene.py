from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_settings_example_has_no_live_secrets() -> None:
    text = (ROOT / "config/settings.example.yaml").read_text(encoding="utf-8")
    assert "sk-" not in text
    assert "-----BEGIN" not in text
