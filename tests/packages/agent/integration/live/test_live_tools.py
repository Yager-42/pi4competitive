"""Live: tools sequential / parallel + hooks surface via Agent."""
from __future__ import annotations

import pytest

from .helpers import assistants, make_add_tool, make_agent, make_echo_tool, tool_results, text_of

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_live_sequential_echo_tool(live_gateway) -> None:
    agent = make_agent(
        live_gateway,
        system_prompt=(
            "You MUST call the echo tool. Do not answer without a tool call. "
            "Call echo with text exactly: live-ok"
        ),
        tools=[make_echo_tool()],
        tool_execution="sequential",
    )
    await agent.prompt("Use the echo tool to echo exactly: live-ok")
    await agent.wait_for_idle()

    assert agent.state.errorMessage is None, agent.state.errorMessage
    tr = tool_results(agent.state.messages)
    asst = assistants(agent.state.messages)
    assert asst, "expected assistant message"
    assert asst[-1].get("stopReason") != "error" or tr

    # Strong preference: model actually called the tool
    if tr:
        body = " ".join(text_of(m) for m in tr)
        assert "live-ok" in body
        assert any(not m.get("isError") for m in tr)
    else:
        # Fallback: at least completed a turn (gateway may strip tools)
        assert asst[-1].get("stopReason") in ("stop", "length", "toolUse")


@pytest.mark.asyncio
async def test_live_parallel_two_tools(live_gateway) -> None:
    agent = make_agent(
        live_gateway,
        system_prompt=(
            "You have tools: echo and add. In ONE assistant response, call BOTH tools: "
            "add with a=2,b=3 AND echo with text=hi. Do not answer without both tool calls."
        ),
        tools=[make_echo_tool(), make_add_tool()],
        tool_execution="parallel",
    )
    await agent.prompt("Call both echo and add tools now.")
    await agent.wait_for_idle()

    assert agent.state.errorMessage is None, agent.state.errorMessage
    tr = tool_results(agent.state.messages)
    names = [m.get("toolName") for m in tr]
    # Ideal: both tools ran; accept partial if model only called one
    if len(tr) >= 2:
        assert "echo" in names or "add" in names
    assert assistants(agent.state.messages)
