"""Live: Agent loop / events / abort."""
from __future__ import annotations

import asyncio

import pytest

from .helpers import EventRecorder, assistants, make_agent, text_of

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_live_agent_text_and_event_order(live_gateway) -> None:
    rec = EventRecorder()
    agent = make_agent(
        live_gateway,
        system_prompt="Reply with exactly the single word: pong",
    )
    agent.subscribe(rec)
    await agent.prompt("Reply with exactly: pong")
    await agent.wait_for_idle()

    assert rec.types[0] == "agent_start"
    assert "turn_start" in rec.types
    assert "message_start" in rec.types
    assert "message_end" in rec.types
    assert rec.types[-1] == "agent_end"
    assert agent.state.isStreaming is False
    assert agent.state.errorMessage is None, agent.state.errorMessage

    last = assistants(agent.state.messages)[-1]
    assert last.get("stopReason") in ("stop", "length", "toolUse")
    assert "pong" in text_of(last).lower() or last.get("stopReason") == "stop"


@pytest.mark.asyncio
async def test_live_agent_abort(live_gateway) -> None:
    agent = make_agent(
        live_gateway,
        system_prompt="Write a long multi-paragraph essay with many sections.",
    )

    async def run() -> None:
        await agent.prompt(
            "Write a very long detailed essay about the history of mathematics, "
            "covering at least twenty named mathematicians and their contributions."
        )

    task = asyncio.create_task(run())
    # Abort shortly after start — path must settle without hanging.
    await asyncio.sleep(0.05)
    agent.abort()
    await asyncio.wait_for(agent.wait_for_idle(), timeout=60)
    if not task.done():
        await asyncio.wait_for(task, timeout=60)

    assert agent.state.isStreaming is False
    # Abort may finish before first token (empty) or produce aborted/error stop.
    msgs = assistants(agent.state.messages)
    if msgs:
        stop = msgs[-1].get("stopReason")
        assert stop in ("stop", "aborted", "error", "length", "toolUse")
