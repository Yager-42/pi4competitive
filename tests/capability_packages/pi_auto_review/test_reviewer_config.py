"""Reviewer config — trusted config, tighten-only project overlay, trust checks.

Source: pi-auto-review@0.3.2 ``trust.test.ts`` (PORT trusted install/config
tighten-only cases) + ``index.ts`` config validation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pi_auto_review.reviewer import (
    PACKAGE_ROOT,
    Config,
    apply_project_config,
    apply_user_config,
    assert_trusted_installation,
    package_config_path,
    session_config,
    validate_config,
)


def _trusted() -> Config:
    return validate_config(
        {
            "model": "codex-auto-review",
            "reasoning": "low",
            "timeoutMs": 45_000,
            "maxTokens": 1_600,
            "retries": 1,
            "maxUserTranscriptTokens": 1_200,
            "maxToolTranscriptTokens": 1_200,
            "maxRelevantResultTokens": 800,
            "failureMode": "deny",
            "grantTtlMs": 60_000,
            "autoConfirmBoundedAllows": ["external_directory", "path"],
        },
        "test",
    )


def test_package_config_is_valid() -> None:
    raw = json.loads(package_config_path().read_text())
    config = validate_config(raw, "package config")
    assert config["failureMode"] == "deny"
    assert config["grantTtlMs"] == 60_000


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        "config",
        42,
    ],
)
def test_validate_config_rejects_non_object(value: object) -> None:
    with pytest.raises(ValueError, match="must be an object"):
        validate_config(value, "test")


def test_validate_config_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="unknown config keys.*nonsense"):
        validate_config({"nonsense": 1}, "test")


@pytest.mark.parametrize(
    "key,value",
    [
        ("model", ""),
        ("model", "with space"),
        ("model", "a/b/c"),
        ("reasoning", "ultra"),
        ("timeoutMs", 500),
        ("timeoutMs", 120_001),
        ("maxTokens", 100),
        ("maxTokens", 5_000),
        ("retries", -1),
        ("retries", 3),
        ("failureMode", "allow"),
        ("grantTtlMs", 0),
        ("grantTtlMs", 400_000),
        ("maxUserTranscriptTokens", 10),
        ("maxToolTranscriptTokens", 10_000),
        ("autoConfirmBoundedAllows", ["path", "path"]),
        ("autoConfirmBoundedAllows", ["network"]),
    ],
)
def test_validate_config_rejects_bad_values(key: str, value: object) -> None:
    with pytest.raises(ValueError):
        validate_config({key: value}, "test")


def test_apply_user_config_can_set_any_key() -> None:
    config = apply_user_config(_trusted(), {"model": "anthropic/claude-review"})
    assert config["model"] == "anthropic/claude-review"


def test_apply_user_config_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="unknown config keys"):
        apply_user_config(_trusted(), {"autoApproveAll": True})


def test_project_config_may_only_tighten_numbers() -> None:
    trusted = _trusted()
    tightened = apply_project_config(trusted, {"timeoutMs": 10_000, "maxTokens": 800})
    assert tightened["timeoutMs"] == 10_000
    assert tightened["maxTokens"] == 800
    assert tightened["model"] == trusted["model"]


def test_project_config_cannot_raise_numbers() -> None:
    with pytest.raises(ValueError, match="may only lower"):
        apply_project_config(_trusted(), {"timeoutMs": 120_000})


def test_project_config_cannot_set_forbidden_keys() -> None:
    with pytest.raises(ValueError, match="cannot set"):
        apply_project_config(_trusted(), {"model": "other"})


def test_project_config_failure_mode_deny_only() -> None:
    assert apply_project_config(_trusted(), {"failureMode": "deny"})["failureMode"] == "deny"
    with pytest.raises(ValueError, match="may only be deny"):
        apply_project_config(_trusted(), {"failureMode": "defer"})


def test_project_config_can_only_remove_trusted_surfaces() -> None:
    config = apply_project_config(_trusted(), {"autoConfirmBoundedAllows": ["path"]})
    assert list(config["autoConfirmBoundedAllows"]) == ["path"]
    with pytest.raises(ValueError, match="may only remove"):
        apply_project_config(_trusted(), {"autoConfirmBoundedAllows": ["network"]})


def test_trusted_installation_rejects_cwd_inside_package(tmp_path: Path) -> None:
    # Simulate a package root and a cwd nested inside it.
    fake_root = tmp_path / "fake-package"
    fake_root.mkdir()
    with pytest.raises(ValueError, match="refusing security policy"):
        assert_trusted_installation(str(fake_root), package_root=fake_root)


def test_trusted_installation_allows_other_cwd(tmp_path: Path) -> None:
    assert_trusted_installation(str(tmp_path), package_root=PACKAGE_ROOT)


def test_session_config_without_project_file(tmp_path: Path) -> None:
    config = session_config(str(tmp_path), _trusted(), allow_untrusted_workspace=True)
    assert config["grantTtlMs"] == _trusted()["grantTtlMs"]


def test_session_config_applies_tighten_only_project_file(tmp_path: Path) -> None:
    (tmp_path / ".pi").mkdir()
    (tmp_path / ".pi" / "pi-auto-review.json").write_text(json.dumps({"timeoutMs": 5_000}))
    config = session_config(str(tmp_path), _trusted(), allow_untrusted_workspace=True)
    assert config["timeoutMs"] == 5_000


def test_session_config_rejects_widening_project_file(tmp_path: Path) -> None:
    (tmp_path / ".pi").mkdir()
    (tmp_path / ".pi" / "pi-auto-review.json").write_text(json.dumps({"timeoutMs": 120_000}))
    with pytest.raises(ValueError, match="may only lower"):
        session_config(str(tmp_path), _trusted(), allow_untrusted_workspace=True)


def test_session_config_asserts_trusted_installation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="refusing security policy"):
        session_config(str(PACKAGE_ROOT), _trusted(), allow_untrusted_workspace=False)
