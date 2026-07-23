from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from earendil_works.pi_ai import create_models
from earendil_works.pi_ai.providers.faux import (
    faux_assistant_message,
    faux_provider,
    faux_text,
    faux_tool_call,
)

from earendil_works.pi_agent import AgentLoopConfig, AgentTool, run_agent_loop
from earendil_works.pi_agent.types import AgentContext, AgentEvent, AgentMessage, AgentToolResult


def _convert_to_llm(messages: list[AgentMessage]) -> list[Any]:
    return [m for m in messages if isinstance(m, dict) and m.get("role") in ("user", "assistant", "toolResult")]


async def _echo_execute(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
) -> AgentToolResult:
    text = str(params.get("text", ""))
    if on_update:
        on_update({"content": [{"type": "text", "text": text[:1]}], "details": {"partial": True}})
    return {"content": [faux_text(text)], "details": {"echoed": text}}


async def _add_execute(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
) -> AgentToolResult:
    a = int(params.get("a", 0))
    b = int(params.get("b", 0))
    return {"content": [faux_text(str(a + b))], "details": {"sum": a + b}}


def _echo_tool() -> AgentTool:
    return AgentTool(
        name="echo",
        description="echo",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        label="Echo",
        execute=_echo_execute,
    )


def _add_tool(*, mode: str | None = None) -> AgentTool:
    return AgentTool(
        name="add",
        description="add",
        parameters={
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
        label="Add",
        execute=_add_execute,
        executionMode=mode,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_tool_echo_then_final_text() -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"](
        [
            faux_assistant_message([faux_tool_call("echo", {"text": "pong"})]),
            faux_assistant_message("done"),
        ]
    )
    model = faux["getModel"]()
    assert model is not None

    events: list[AgentEvent] = []

    async def emit(event: AgentEvent) -> None:
        events.append(event)

    tools = [_echo_tool()]
    context: AgentContext = {"systemPrompt": "test", "messages": [], "tools": tools}
    cfg = AgentLoopConfig(model=model, convertToLlm=_convert_to_llm, toolExecution="sequential")
    prompt: AgentMessage = {"role": "user", "content": "echo please", "timestamp": int(time.time() * 1000)}

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
    assert any(c.get("text") == "pong" for c in content if isinstance(c, dict))

    assistants = [m for m in new_messages if isinstance(m, dict) and m.get("role") == "assistant"]
    assert assistants[-1].get("stopReason") == "stop"


@pytest.mark.asyncio
async def test_blocked_tool_emits_error_result() -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"](
        [
            faux_assistant_message([faux_tool_call("echo", {"text": "nope"})]),
            faux_assistant_message("ok"),
        ]
    )
    model = faux["getModel"]()
    assert model is not None

    async def before(ctx, signal=None):  # type: ignore[no-untyped-def]
        return {"block": True, "reason": "blocked by test"}

    events: list[AgentEvent] = []
    cfg = AgentLoopConfig(
        model=model,
        convertToLlm=_convert_to_llm,
        beforeToolCall=before,
        toolExecution="sequential",
    )
    context: AgentContext = {
        "systemPrompt": "t",
        "messages": [],
        "tools": [_echo_tool()],
    }
    prompt: AgentMessage = {"role": "user", "content": "x", "timestamp": 0}
    new_messages = await run_agent_loop(
        [prompt], context, cfg, events.append, None, models.streamSimple
    )
    tool_results = [m for m in new_messages if isinstance(m, dict) and m.get("role") == "toolResult"]
    assert tool_results[0]["isError"] is True
    text = " ".join(
        c.get("text", "") for c in tool_results[0]["content"] if isinstance(c, dict)
    )
    assert "blocked" in text.lower()


@pytest.mark.asyncio
async def test_parallel_two_tools_source_order_results() -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"](
        [
            faux_assistant_message(
                [
                    faux_tool_call("add", {"a": 1, "b": 2}, id="c1"),
                    faux_tool_call("echo", {"text": "z"}, id="c2"),
                ]
            ),
            faux_assistant_message("finished"),
        ]
    )
    model = faux["getModel"]()
    assert model is not None

    slow_add_started = asyncio.Event()
    allow_add = asyncio.Event()

    async def slow_add(tool_call_id, params, signal=None, on_update=None):  # type: ignore[no-untyped-def]
        slow_add_started.set()
        await allow_add.wait()
        return await _add_execute(tool_call_id, params, signal, on_update)

    tools = [
        AgentTool(
            name="add",
            description="add",
            parameters={
                "type": "object",
                "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                "required": ["a", "b"],
            },
            label="Add",
            execute=slow_add,
        ),
        _echo_tool(),
    ]
    context: AgentContext = {"systemPrompt": "t", "messages": [], "tools": tools}
    cfg = AgentLoopConfig(model=model, convertToLlm=_convert_to_llm, toolExecution="parallel")

    async def run() -> list[AgentMessage]:
        return await run_agent_loop(
            [{"role": "user", "content": "both", "timestamp": 0}],
            context,
            cfg,
            lambda e: None,
            None,
            models.streamSimple,
        )

    task = asyncio.create_task(run())
    await slow_add_started.wait()
    # Let echo finish first while add is held
    await asyncio.sleep(0.05)
    allow_add.set()
    new_messages = await task

    tool_results = [m for m in new_messages if isinstance(m, dict) and m.get("role") == "toolResult"]
    assert [m["toolCallId"] for m in tool_results] == ["c1", "c2"]
    assert [m["toolName"] for m in tool_results] == ["add", "echo"]
