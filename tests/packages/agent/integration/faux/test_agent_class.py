from __future__ import annotations

import pytest
from earendil_works.pi_ai import create_models
from earendil_works.pi_ai.providers.faux import faux_assistant_message, faux_provider

from earendil_works.pi_agent.agent import Agent, AgentOptions
from earendil_works.pi_agent.types import AgentEvent


@pytest.mark.asyncio
async def test_agent_prompt_subscribe_and_idle() -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"]([faux_assistant_message("pong")])
    model = faux["getModel"]()
    assert model is not None

    agent = Agent(
        AgentOptions(
            stream_fn=models.streamSimple,
            initial_state={"systemPrompt": "test", "model": model},
        )
    )
    events: list[str] = []

    def on_event(event: AgentEvent, signal) -> None:  # type: ignore[no-untyped-def]
        events.append(event["type"])

    unsub = agent.subscribe(on_event)
    await agent.prompt("ping")
    await agent.wait_for_idle()

    assert agent.state.isStreaming is False
    assert events[0] == "agent_start"
    assert events[-1] == "agent_end"
    assert "message_update" in events
    roles = [
        m.get("role") for m in agent.state.messages if isinstance(m, dict)
    ]
    assert roles[0] == "user"
    assert roles[-1] == "assistant"
    unsub()


@pytest.mark.asyncio
async def test_agent_tools_and_state_messages_grow() -> None:
    from earendil_works.pi_ai.providers.faux import faux_text, faux_tool_call
    from earendil_works.pi_agent import AgentTool

    async def echo(tool_call_id, params, signal=None, on_update=None):  # type: ignore[no-untyped-def]
        return {"content": [faux_text(str(params.get("text", "")))], "details": {}}

    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"](
        [
            faux_assistant_message([faux_tool_call("echo", {"text": "hi"})]),
            faux_assistant_message("done"),
        ]
    )
    model = faux["getModel"]()
    tool = AgentTool(
        name="echo",
        description="e",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        label="Echo",
        execute=echo,
    )
    agent = Agent(
        AgentOptions(
            stream_fn=models.streamSimple,
            initial_state={"model": model, "tools": [tool], "systemPrompt": "t"},
            tool_execution="sequential",
        )
    )
    await agent.prompt("use tool")
    await agent.wait_for_idle()
    roles = [m.get("role") for m in agent.state.messages if isinstance(m, dict)]
    assert "toolResult" in roles
    assert roles[-1] == "assistant"


@pytest.mark.asyncio
async def test_agent_reset_clears_messages() -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"]([faux_assistant_message("x")])
    model = faux["getModel"]()
    agent = Agent(AgentOptions(stream_fn=models.streamSimple, initial_state={"model": model}))
    await agent.prompt("a")
    assert agent.state.messages
    agent.reset()
    assert agent.state.messages == []
    assert agent.has_queued_messages() is False


@pytest.mark.asyncio
async def test_follow_up_queue_drains_after_turn() -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    # first response ends turn; follow-up should trigger second assistant reply
    faux["setResponses"](
        [
            faux_assistant_message("first"),
            faux_assistant_message("second"),
        ]
    )
    model = faux["getModel"]()
    agent = Agent(
        AgentOptions(
            stream_fn=models.streamSimple,
            initial_state={"model": model},
            follow_up_mode="all",
        )
    )
    agent.follow_up({"role": "user", "content": "more", "timestamp": 0})
    await agent.prompt("start")
    await agent.wait_for_idle()
    assistants = [
        m for m in agent.state.messages if isinstance(m, dict) and m.get("role") == "assistant"
    ]
    assert len(assistants) >= 2
