from __future__ import annotations

from typing import Any, get_args

import pytest
from earendil_works.pi_ai import validate_tool_arguments
from earendil_works.pi_ai.types import empty_usage
from earendil_works.pi_ai.utils.validation import ValidationError

from earendil_works.pi_agent import (
    AgentLoopConfig,
    AgentTool,
    QueueMode,
    ToolExecutionMode,
    get_default_stream_fn,
    set_default_stream_fn,
)
from earendil_works.pi_agent.types import AgentEvent, AgentToolResult


def test_tool_execution_mode_literals() -> None:
    assert set(get_args(ToolExecutionMode)) == {"sequential", "parallel"}


def test_queue_mode_literals() -> None:
    assert set(get_args(QueueMode)) == {"all", "one-at-a-time"}


def test_agent_event_type_tags() -> None:
    events: list[AgentEvent] = [
        {"type": "agent_start"},
        {"type": "agent_end", "messages": []},
        {"type": "turn_start"},
        {
            "type": "turn_end",
            "message": {
                "role": "assistant",
                "content": [],
                "api": "faux",
                "provider": "faux",
                "model": "faux",
                "usage": empty_usage(),
                "stopReason": "stop",
                "timestamp": 0,
            },
            "toolResults": [],
        },
        {
            "type": "message_start",
            "message": {"role": "user", "content": "hi", "timestamp": 0},
        },
        {
            "type": "message_end",
            "message": {"role": "user", "content": "hi", "timestamp": 0},
        },
        {
            "type": "tool_execution_start",
            "toolCallId": "1",
            "toolName": "echo",
            "args": {},
        },
        {
            "type": "tool_execution_end",
            "toolCallId": "1",
            "toolName": "echo",
            "result": {"content": [], "details": None},
            "isError": False,
        },
    ]
    assert [e["type"] for e in events] == [
        "agent_start",
        "agent_end",
        "turn_start",
        "turn_end",
        "message_start",
        "message_end",
        "tool_execution_start",
        "tool_execution_end",
    ]


async def _echo_execute(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
) -> AgentToolResult:
    text = str(params.get("text", ""))
    return {
        "content": [{"type": "text", "text": text}],
        "details": {"echoed": text},
    }


async def test_agent_tool_to_llm_tool_and_execute() -> None:
    tool = AgentTool(
        name="echo",
        description="echo text",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
        label="Echo",
        execute=_echo_execute,
    )
    llm = tool.to_llm_tool()
    assert llm["name"] == "echo"
    assert llm["parameters"]["required"] == ["text"]

    args = validate_tool_arguments(tool.parameters, {"text": "pong"})
    result = await tool.execute("tc1", args, None, None)
    assert result["content"][0]["text"] == "pong"  # type: ignore[index]


def test_tool_schema_validation_missing_required() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "number"}},
        "required": ["a"],
    }
    with pytest.raises(ValidationError):
        validate_tool_arguments(schema, {})


def test_agent_loop_config_to_stream_options() -> None:
    model = {
        "id": "faux",
        "name": "faux",
        "api": "faux",
        "provider": "faux",
        "baseUrl": "",
        "reasoning": False,
        "input": ["text"],
        "cost": {"input": 0.0, "output": 0.0, "cacheRead": 0.0, "cacheWrite": 0.0},
        "contextWindow": 128000,
        "maxTokens": 4096,
    }
    cfg = AgentLoopConfig(
        model=model,  # type: ignore[arg-type]
        convertToLlm=lambda msgs: list(msgs),  # type: ignore[arg-type,return-value]
        temperature=0.2,
        maxTokens=100,
        reasoning="low",
    )
    opts = cfg.to_stream_options()
    assert opts["temperature"] == 0.2
    assert opts["maxTokens"] == 100
    assert opts["reasoning"] == "low"


def test_default_stream_fn_roundtrip() -> None:
    assert get_default_stream_fn() is None

    def fake_stream(model, context, options=None):  # type: ignore[no-untyped-def]
        raise AssertionError("not called")

    set_default_stream_fn(fake_stream)
    assert get_default_stream_fn() is fake_stream
    set_default_stream_fn(None)
    assert get_default_stream_fn() is None
