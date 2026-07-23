"""C1 exit: load echo_example → Agent/loop(faux) toolResult."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from earendil_works.pi_ai import create_models
from earendil_works.pi_ai.providers.faux import (
    faux_assistant_message,
    faux_provider,
    faux_tool_call,
)

from earendil_works.pi_agent import (
    Agent,
    AgentOptions,
    AgentLoopConfig,
    apply_capability_report,
    load_capability_packages,
    run_agent_loop,
)
from earendil_works.pi_agent.types import AgentContext, AgentEvent, AgentMessage, AgentTool

ROOT = Path(__file__).resolve().parents[4]
CAP_ROOT = ROOT / "capability_packages"


def _convert_to_llm(messages: list[AgentMessage]) -> list[Any]:
    return [m for m in messages if isinstance(m, dict) and m.get("role") in ("user", "assistant", "toolResult")]


@pytest.mark.asyncio
async def test_load_echo_and_direct_execute() -> None:
    report = await load_capability_packages(root=CAP_ROOT, enabled=["echo_example"])
    assert "echo" in report.tool_names()
    assert not any(d.level == "error" for d in report.diagnostics), report.diagnostics

    echo = next(t for t in report.tools if t.name == "echo")
    assert isinstance(echo, AgentTool)
    result = await echo.execute("tid1", {"text": "hello-capability"})
    texts = [c.get("text") for c in result.get("content", []) if isinstance(c, dict)]
    assert "hello-capability" in texts
    assert result.get("details", {}).get("package") == "echo_example"

    agent = Agent(AgentOptions(initial_state={"tools": [], "systemPrompt": "x"}))
    apply_capability_report(agent, report)
    assert any(t.name == "echo" for t in agent.state.tools)


@pytest.mark.asyncio
async def test_agent_loop_calls_capability_echo_tool() -> None:
    """Full faux loop: assistant toolCall → toolResult from capability package tool."""
    report = await load_capability_packages(root=CAP_ROOT, enabled=["echo_example"])
    tools = list(report.tools)
    assert any(t.name == "echo" for t in tools)

    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"](
        [
            faux_assistant_message([faux_tool_call("echo", {"text": "from-loop"})]),
            faux_assistant_message("done"),
        ]
    )
    model = faux["getModel"]()
    assert model is not None

    events: list[AgentEvent] = []

    async def emit(event: AgentEvent) -> None:
        events.append(event)

    context: AgentContext = {"systemPrompt": "test", "messages": [], "tools": tools}
    cfg = AgentLoopConfig(model=model, convertToLlm=_convert_to_llm, toolExecution="sequential")
    prompt: AgentMessage = {
        "role": "user",
        "content": "echo please",
        "timestamp": int(time.time() * 1000),
    }

    new_messages = await run_agent_loop(
        [prompt], context, cfg, emit, None, models.streamSimple
    )

    types = [e["type"] for e in events]
    assert "tool_execution_start" in types
    assert "tool_execution_end" in types
    assert types[0] == "agent_start"
    assert types[-1] == "agent_end"

    tool_results = [m for m in new_messages if isinstance(m, dict) and m.get("role") == "toolResult"]
    assert len(tool_results) == 1
    assert tool_results[0]["isError"] is False
    content = tool_results[0]["content"]
    assert any(c.get("text") == "from-loop" for c in content if isinstance(c, dict))

    assistants = [m for m in new_messages if isinstance(m, dict) and m.get("role") == "assistant"]
    assert assistants[-1].get("stopReason") == "stop"
