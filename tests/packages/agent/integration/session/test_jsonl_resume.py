from __future__ import annotations

from pathlib import Path

import pytest

from earendil_works.pi_agent.harness.env.python_env import LocalFileSystem
from earendil_works.pi_agent.harness.session import DEFAULT_SESSIONS_DIR_NAME, JsonlSessionRepo
from earendil_works.pi_agent.harness.session.session import DEFAULT_SESSIONS_DIR_NAME as DEFAULT_NAME


@pytest.mark.asyncio
async def test_jsonl_write_reopen_same_context(tmp_path: Path) -> None:
    sessions_root = tmp_path / DEFAULT_SESSIONS_DIR_NAME
    sessions_root.mkdir(parents=True)
    fs = LocalFileSystem(cwd=str(tmp_path))
    repo = JsonlSessionRepo({"fs": fs, "sessionsRoot": str(sessions_root)})

    session = await repo.create({"cwd": str(tmp_path)})
    await session.append_message({"role": "user", "content": "persist-me", "timestamp": 1})
    await session.append_message(
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "stored"}],
            "api": "faux",
            "provider": "faux",
            "model": "m1",
            "usage": {
                "input": 1,
                "output": 1,
                "cacheRead": 0,
                "cacheWrite": 0,
                "totalTokens": 2,
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0},
            },
            "stopReason": "stop",
            "timestamp": 2,
        }
    )
    meta = await session.get_metadata()
    assert meta["path"].endswith(".jsonl")
    assert DEFAULT_SESSIONS_DIR_NAME in meta["path"] or "sessions" in meta["path"]

    reopened = await repo.open(meta)
    ctx = await reopened.build_context()
    assert len(ctx["messages"]) == 2
    assert ctx["messages"][0]["content"] == "persist-me"  # type: ignore[index]
    assert ctx["model"] == {"provider": "faux", "modelId": "m1"}


@pytest.mark.asyncio
async def test_jsonl_list_and_default_path_layout(tmp_path: Path) -> None:
    sessions_root = tmp_path / "data" / "sessions"
    fs = LocalFileSystem(cwd=str(tmp_path))
    repo = JsonlSessionRepo({"fs": fs, "sessionsRoot": str(sessions_root)})
    s1 = await repo.create({"cwd": "/workspace"})
    await s1.append_message({"role": "user", "content": "a", "timestamp": 1})
    listed = await repo.list({"cwd": "/workspace"})
    assert len(listed) == 1
    assert listed[0]["cwd"] == "/workspace"
    assert DEFAULT_NAME == "data/sessions"


@pytest.mark.asyncio
async def test_jsonl_fork_new_leaf(tmp_path: Path) -> None:
    sessions_root = tmp_path / "data" / "sessions"
    fs = LocalFileSystem(cwd=str(tmp_path))
    repo = JsonlSessionRepo({"fs": fs, "sessionsRoot": str(sessions_root)})
    session = await repo.create({"cwd": str(tmp_path)})
    first = await session.append_message({"role": "user", "content": "keep", "timestamp": 1})
    await session.append_message({"role": "user", "content": "drop", "timestamp": 2})
    meta = await session.get_metadata()
    forked = await repo.fork(meta, {"cwd": str(tmp_path), "entryId": first, "position": "at"})
    ctx = await forked.build_context()
    assert len(ctx["messages"]) == 1
    assert ctx["messages"][0]["content"] == "keep"  # type: ignore[index]
    # source intact
    source_ctx = await (await repo.open(meta)).build_context()
    assert len(source_ctx["messages"]) == 2
