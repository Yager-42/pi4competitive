"""Focused checks for the standalone comparison/verification scripts."""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str, **env: str):
    import os

    previous = os.environ.copy()
    os.environ.update(env)
    try:
        path = ROOT / "scripts" / name
        spec = importlib.util.spec_from_file_location(f"known_{name.replace('.', '_')}", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        os.environ.clear()
        os.environ.update(previous)


def test_group_session_helper_awaits_repo_open(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SESSIONS_CWD", "comp_test")
    module = load_script(
        "_run_one_group.py",
        GROUP_LABEL="test",
        GROUP_REPO=str(ROOT),
        GROUP_STOP_AFTER="collect",
        GROUP_TRACE="test",
        GROUP_BRIEF=json.dumps({"research_brief": {}}),
        GROUP_OUT=str(ROOT / "data" / "test-script-check"),
    )

    class Repo:
        async def list(self, _query):
            return [{"id": "sid", "cwd": "comp_test"}]

        async def open(self, metadata):
            self.opened = metadata
            return "session"

    class State:
        repo = Repo()

    session = asyncio.run(module._open_session(State(), "sid"))
    assert session == "session"
    assert State.repo.opened["id"] == "sid"


def test_postprocess_creates_output_parent(tmp_path):
    module = load_script("comparison_postprocess.py")
    module.ROOT = tmp_path
    module.WORKTREE = tmp_path / "worktree"
    module.OUT = tmp_path / "nested" / "comparison"
    module.main()
    assert (module.OUT / "comparison_stats.json").is_file()


def test_resume_preparation_uses_public_service_api(tmp_path):
    """The resume script must drive the public service transaction, not a
    script-local reimplementation of the resume rules."""
    module = load_script(
        "resume_to_report.py",
        RESUME_REPO=str(ROOT),
        RESUME_TASK_ID="task-1",
        RESUME_SESSION_ID="session-1",
        RESUME_APP_DB=str(tmp_path / "unused.db"),
        RESUME_SESSIONS_ROOT=str(tmp_path / "sessions"),
        RESUME_SESSIONS_CWD="test",
        RESUME_OUT=str(tmp_path / "out"),
        RESUME_ARCH="three",
    )

    class Service:
        def __init__(self):
            self.prepared: list[str] = []

        async def prepare_resume_task(self, task_id):
            self.prepared.append(task_id)
            return {"task_id": task_id, "status": "pending"}

    service = Service()
    state = type("State", (), {"task_service": service})()
    asyncio.run(module.prepare_task_for_resume(state))
    assert service.prepared == ["task-1"]


def test_docker_context_keeps_nested_vendor_tree():
    patterns = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "vendor/*" in patterns
    assert "vendor" not in patterns

def test_fetch_upstream_no_args_expands_three_packages(tmp_path):
    script_root = tmp_path / "repo"
    scripts = script_root / "scripts"
    plans = script_root / "docs" / "plans"
    scripts.mkdir(parents=True)
    plans.mkdir(parents=True)
    (scripts / "fetch_upstream.sh").write_bytes(
        (ROOT / "scripts" / "fetch_upstream.sh").read_bytes()
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "git").write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$GIT_LOG\"\n"
        "if [[ $1 == clone ]]; then dest=\"${@: -1}\"; mkdir -p \"$dest\"; fi\n"
        "if [[ $1 == -C && $3 == rev-parse ]]; then echo deadbeef; fi\n",
        encoding="utf-8",
    )
    (fake_bin / "git").chmod(0o755)
    import os
    import subprocess

    log = tmp_path / "git.log"
    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "GIT_LOG": str(log)}
    subprocess.run(["bash", str(scripts / "fetch_upstream.sh")], env=env, check=True)
    calls = log.read_text(encoding="utf-8")
    assert "packages/ai packages/agent packages/coding-agent" in calls
