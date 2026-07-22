from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_packages_ai_path_exists() -> None:
    assert (ROOT / "packages/ai/src/earendil_works/pi_ai").is_dir()


def test_import_name_earendil_works_pi_ai() -> None:
    import earendil_works.pi_ai as pi_ai

    assert pi_ai.__name__ == "earendil_works.pi_ai"


def test_no_top_level_pi_core_package() -> None:
    assert not (ROOT / "packages/pi_core").exists()
    assert not (ROOT / "packages/ai/src/pi_core").exists()


def test_capability_packages_not_inside_ai() -> None:
    ai = ROOT / "packages/ai"
    assert not (ai / "capability_packages").exists()


def test_data_sessions_not_required_for_ai_import() -> None:
    import earendil_works.pi_ai as pi_ai

    assert pi_ai is not None
