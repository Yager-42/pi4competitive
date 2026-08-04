"""Focused checks for the standalone comparison/verification scripts."""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str, **env: str):
    import os

    os.environ.update(env)
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(f"known_{name.replace('.', '_')}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_group_session_helper_awaits_repo_open():
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


def test_resume_preparation_uses_shared_validation(tmp_path):
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

    class Registry:
        def task_active(self, _task_id):
            return False

    class Store:
        def __init__(self):
            self.metadata = None
            self.status = None

        async def update_task_metadata(self, _task_id, metadata):
            self.metadata = metadata

        async def update_task_status(self, _task_id, status):
            self.status = status
            return True

    class Service:
        async def get_task(self, _task_id):
            return {
                "task_id": "task-1",
                "status": "completed",
                "session_id": "session-1",
                "metadata": {"stop_after_stage": "search", "trace": "t"},
                "projection": {"stages": {"search": "ok", "write": "pending"}},
            }

        def _first_non_ok_stage(self, projection):
            stages = (projection or {}).get("stages") or {}
            return next((name for name in ("search", "write") if stages.get(name) != "ok"), None)

        async def _load_research_brief(self, _session_id):
            return {"research_brief": {}}
    state = type("State", (), {"registry": Registry(), "store": Store(), "task_service": Service()})()
    asyncio.run(module.prepare_task_for_resume(state))
    assert state.store.status == "pending"
    assert "stop_after_stage" not in state.store.metadata

    async def missing_task(_task_id):
        raise RuntimeError("task not found")

    state.task_service.get_task = missing_task
    try:
        asyncio.run(module.prepare_task_for_resume(state))
    except RuntimeError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("unknown task id must be rejected")

    async def no_session(_task_id):
        return {"status": "completed", "metadata": {"stop_after_stage": "search"}}

    state.task_service.get_task = no_session
    try:
        asyncio.run(module.prepare_task_for_resume(state))
    except RuntimeError as exc:
        assert "no session" in str(exc)
    else:
        raise AssertionError("missing session must be rejected")

    async def no_brief(_session_id):
        return None

    state.task_service.get_task = Service().get_task
    state.task_service._load_research_brief = no_brief
    try:
        asyncio.run(module.prepare_task_for_resume(state))
    except RuntimeError as exc:
        assert "brief not recoverable" in str(exc)
    else:
        raise AssertionError("unrecoverable brief must be rejected")


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
