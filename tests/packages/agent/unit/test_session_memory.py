from __future__ import annotations

import pytest

from earendil_works.pi_agent.harness.session import (
    InMemorySessionRepo,
    build_session_context,
)


@pytest.mark.asyncio
async def test_memory_append_and_build_context() -> None:
    repo = InMemorySessionRepo()
    session = await repo.create()
    await session.append_message({"role": "user", "content": "hi", "timestamp": 1})
    await session.append_message(
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "hello"}],
            "api": "faux",
            "provider": "faux",
            "model": "faux-1",
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
    ctx = await session.build_context()
    assert len(ctx["messages"]) == 2
    assert ctx["messages"][0]["role"] == "user"  # type: ignore[index]
    assert ctx["model"] == {"provider": "faux", "modelId": "faux-1"}
    stats = await session.get_session_stats()
    assert stats["messageCount"] == 2


@pytest.mark.asyncio
async def test_memory_fork_preserves_prefix() -> None:
    repo = InMemorySessionRepo()
    session = await repo.create({"id": "src"})
    uid = await session.append_message({"role": "user", "content": "a", "timestamp": 1})
    await session.append_message({"role": "user", "content": "b", "timestamp": 2})
    meta = await session.get_metadata()
    forked = await repo.fork(meta, {"entryId": uid, "position": "at"})
    branch = await forked.get_branch()
    msgs = [e for e in branch if e.get("type") == "message"]
    assert len(msgs) == 1
    assert msgs[0]["message"]["content"] == "a"  # type: ignore[index]


@pytest.mark.asyncio
async def test_move_to_branches_without_destroying_parent() -> None:
    repo = InMemorySessionRepo()
    session = await repo.create()
    a = await session.append_message({"role": "user", "content": "root", "timestamp": 1})
    await session.append_message({"role": "user", "content": "child", "timestamp": 2})
    await session.move_to(a, {"summary": "went back"})
    await session.append_message({"role": "user", "content": "new-branch", "timestamp": 3})
    branch = await session.get_branch()
    texts = []
    for e in branch:
        if e.get("type") == "message":
            texts.append(e["message"]["content"])  # type: ignore[index]
        if e.get("type") == "branch_summary":
            texts.append("SUMMARY")
    assert "root" in texts
    assert "new-branch" in texts
    assert "SUMMARY" in texts
    # parent history still in storage
    all_entries = await session.get_entries()
    assert any(
        e.get("type") == "message" and e["message"]["content"] == "child"  # type: ignore[index]
        for e in all_entries
    )


def test_build_session_context_helper() -> None:
    entries = [
        {
            "type": "message",
            "id": "1",
            "parentId": None,
            "timestamp": "t",
            "message": {"role": "user", "content": "x", "timestamp": 0},
        }
    ]
    ctx = build_session_context(entries)  # type: ignore[arg-type]
    assert len(ctx["messages"]) == 1
