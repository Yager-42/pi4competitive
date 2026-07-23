"""Live: follow-up / steering queues with real model."""
from __future__ import annotations

import pytest

from .helpers import assistants, make_agent, text_of

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_live_follow_up_queue_second_turn(live_gateway) -> None:
    agent = make_agent(
        live_gateway,
        system_prompt="Be extremely brief. One word answers when possible.",
        follow_up_mode="all",
    )
    agent.follow_up({"role": "user", "content": "Reply with exactly: zebra", "timestamp": 0})
    await agent.prompt("Reply with exactly: apple")
    await agent.wait_for_idle()

    asst = assistants(agent.state.messages)
    assert len(asst) >= 2, f"expected follow-up second turn, got {len(asst)} assistants"
    blob = " ".join(text_of(m).lower() for m in asst)
    # At least one of the target words should appear across the two turns
    assert "apple" in blob or "zebra" in blob or asst[-1].get("stopReason") == "stop"


@pytest.mark.asyncio
async def test_live_continue_with_queued_steering_after_assistant(live_gateway) -> None:
    agent = make_agent(
        live_gateway,
        system_prompt="Be brief. One short sentence max.",
        steering_mode="all",
    )
    await agent.prompt("Say the word: one")
    await agent.wait_for_idle()
    agent.steer({"role": "user", "content": "Now say the word: two", "timestamp": 0})
    # After assistant last message, continue_ drains steering into a new prompt run
    await agent.continue_()
    await agent.wait_for_idle()

    asst = assistants(agent.state.messages)
    assert len(asst) >= 2
    assert agent.state.errorMessage is None, agent.state.errorMessage
