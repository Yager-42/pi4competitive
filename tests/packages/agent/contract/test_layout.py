from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_packages_agent_path_exists() -> None:
    assert (ROOT / "packages/agent/src/earendil_works/pi_agent").is_dir()


def test_import_name_earendil_works_pi_agent() -> None:
    import earendil_works.pi_agent as pi_agent

    assert pi_agent.__name__ == "earendil_works.pi_agent"
    assert pi_agent.__version__ == "0.81.1"


def test_pi_ai_still_importable() -> None:
    import earendil_works.pi_ai as pi_ai

    assert pi_ai.__name__ == "earendil_works.pi_ai"


def test_no_capability_packages_inside_agent() -> None:
    agent = ROOT / "packages/agent"
    assert not (agent / "capability_packages").exists()


def test_no_competitive_app_inside_agent() -> None:
    agent = ROOT / "packages/agent"
    assert not (agent / "competitive_app").exists()
    assert not (agent / "src/competitive_app").exists()


def test_default_sessions_dir_name_contract() -> None:
    from earendil_works.pi_agent.harness.session.session import DEFAULT_SESSIONS_DIR_NAME

    assert DEFAULT_SESSIONS_DIR_NAME == "data/sessions"
