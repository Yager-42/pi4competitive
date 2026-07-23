"""Live: multi-turn agent + JSONL SoT + branch/resume under data/sessions."""
from __future__ import annotations

from pathlib import Path

import pytest

from earendil_works.pi_agent import JsonlSessionRepo
from earendil_works.pi_agent.harness.env.python_env import LocalFileSystem

from .helpers import assistants, make_agent, text_of

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_live_jsonl_multi_turn_resume(live_gateway, tmp_path: Path) -> None:
    agent = make_agent(
        live_gateway,
        system_prompt="Be brief. Answer in a few words only.",
    )
    await agent.prompt("What is 1+1? Reply with just the number.")
    await agent.wait_for_idle()
    await agent.prompt("What is 2+2? Reply with just the number.")
    await agent.wait_for_idle()

    assert len(assistants(agent.state.messages)) >= 2

    sessions_root = tmp_path / "data" / "sessions"
    fs = LocalFileSystem(cwd=str(tmp_path))
    repo = JsonlSessionRepo({"fs": fs, "sessionsRoot": str(sessions_root)})
    session = await repo.create({"cwd": str(tmp_path)})
    for msg in agent.state.messages:
        await session.append_message(msg)

    meta = await session.get_metadata()
    assert "sessions" in meta["path"]
    reopened = await repo.open(meta)
    ctx = await reopened.build_context()
    assert len(ctx["messages"]) == len(agent.state.messages)
    assert Path(meta["path"]).is_file()

    # Branch: move to first user message leaf path and append new branch summary
    entries = await reopened.get_entries()
    user_entries = [
        e
        for e in entries
        if e.get("type") == "message"
        and isinstance(e.get("message"), dict)
        and e["message"].get("role") == "user"
    ]
    assert user_entries
    first_user_id = user_entries[0]["id"]
    await reopened.move_to(first_user_id, {"summary": "live-branch-summary"})
    branch = await reopened.get_branch()
    assert any(e.get("type") == "branch_summary" for e in branch)
    # Parent history still in full log
    all_entries = await reopened.get_entries()
    assert len(all_entries) > len(branch) or any(
        e.get("type") == "message" for e in all_entries
    )


@pytest.mark.asyncio
async def test_live_tool_transcript_jsonl_roundtrip(live_gateway, tmp_path: Path) -> None:
    from .helpers import make_echo_tool, tool_results

    agent = make_agent(
        live_gateway,
        system_prompt="You MUST use the echo tool with text: roundtrip",
        tools=[make_echo_tool()],
    )
    await agent.prompt("Echo roundtrip via the tool")
    await agent.wait_for_idle()

    sessions_root = tmp_path / "data" / "sessions"
    repo = JsonlSessionRepo(
        {"fs": LocalFileSystem(cwd=str(tmp_path)), "sessionsRoot": str(sessions_root)}
    )
    session = await repo.create({"cwd": str(tmp_path)})
    for msg in agent.state.messages:
        await session.append_message(msg)
    ctx = await (await repo.open(await session.get_metadata())).build_context()
    roles = [m.get("role") for m in ctx["messages"] if isinstance(m, dict)]
    assert "user" in roles and "assistant" in roles
    # toolResult only if model cooperated
    if tool_results(agent.state.messages):
        assert "toolResult" in roles
    assert any(text_of(m) for m in assistants(ctx["messages"]))
