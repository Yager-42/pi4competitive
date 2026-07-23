from __future__ import annotations

import time
from typing import Any

import pytest
from earendil_works.pi_ai import create_models
from earendil_works.pi_ai.providers.faux import faux_assistant_message, faux_provider

from earendil_works.pi_agent import AgentLoopConfig, run_agent_loop
from earendil_works.pi_agent.types import AgentContext, AgentEvent, AgentMessage


def _convert_to_llm(messages: list[AgentMessage]) -> list[Any]:
    out: list[Any] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        if m.get("role") in ("user", "assistant", "toolResult"):
            out.append(m)
    return out


@pytest.mark.asyncio
async def test_text_only_event_order() -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"]([faux_assistant_message("hello agent")])
    model = faux["getModel"]()
    assert model is not None

    events: list[AgentEvent] = []

    async def emit(event: AgentEvent) -> None:
        events.append(event)

    context: AgentContext = {"systemPrompt": "you are a test", "messages": []}
    cfg = AgentLoopConfig(model=model, convertToLlm=_convert_to_llm)
    prompt: AgentMessage = {
        "role": "user",
        "content": "hi",
        "timestamp": int(time.time() * 1000),
    }

    new_messages = await run_agent_loop(
        [prompt],
        context,
        cfg,
        emit,
        None,
        models.streamSimple,
    )

    types = [e["type"] for e in events]
    assert types[0] == "agent_start"
    assert types[1] == "turn_start"
    # prompt message_start/end
    assert types[2] == "message_start"
    assert types[3] == "message_end"
    # assistant stream
    assert "message_start" in types[4:]
    assert "message_update" in types
    assert types[-2] == "turn_end"
    assert types[-1] == "agent_end"

    assert new_messages[0] is prompt
    assistant = new_messages[-1]
    assert isinstance(assistant, dict)
    assert assistant.get("role") == "assistant"
    assert assistant.get("stopReason") == "stop"
    text_blocks = [
        b for b in assistant.get("content") or [] if isinstance(b, dict) and b.get("type") == "text"
    ]
    assert any("hello" in (b.get("text") or "") for b in text_blocks)
