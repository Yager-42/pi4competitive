"""Helpers for P2 live module coverage. Never log secrets."""
from __future__ import annotations

from typing import Any, Callable

from earendil_works.pi_agent import Agent, AgentOptions, AgentTool
from earendil_works.pi_agent.types import AgentEvent, AgentMessage


def text_of(message: dict[str, Any] | AgentMessage) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return ""


def assistants(messages: list[Any]) -> list[dict[str, Any]]:
    return [m for m in messages if isinstance(m, dict) and m.get("role") == "assistant"]


def tool_results(messages: list[Any]) -> list[dict[str, Any]]:
    return [m for m in messages if isinstance(m, dict) and m.get("role") == "toolResult"]


def make_agent(
    live_gateway: dict[str, Any],
    *,
    system_prompt: str,
    tools: list[AgentTool] | None = None,
    tool_execution: str = "sequential",
    follow_up_mode: str = "all",
    steering_mode: str = "all",
) -> Agent:
    return Agent(
        AgentOptions(
            stream_fn=live_gateway["models"].streamSimple,
            initial_state={
                "model": live_gateway["model"],
                "tools": tools or [],
                "systemPrompt": system_prompt,
            },
            get_api_key=lambda _p: live_gateway["api_key"],
            tool_execution=tool_execution,  # type: ignore[arg-type]
            follow_up_mode=follow_up_mode,  # type: ignore[arg-type]
            steering_mode=steering_mode,  # type: ignore[arg-type]
        )
    )


def make_echo_tool() -> AgentTool:
    async def execute(
        tool_call_id: str,
        params: dict[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> dict[str, Any]:
        text = str(params.get("text", ""))
        return {"content": [{"type": "text", "text": text}], "details": {"echoed": text}}

    return AgentTool(
        name="echo",
        description="Echo back the given text. Always use this tool when asked to echo.",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        label="Echo",
        execute=execute,
    )


def make_add_tool() -> AgentTool:
    async def execute(
        tool_call_id: str,
        params: dict[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> dict[str, Any]:
        a = int(params.get("a", 0))
        b = int(params.get("b", 0))
        return {
            "content": [{"type": "text", "text": str(a + b)}],
            "details": {"sum": a + b},
        }

    return AgentTool(
        name="add",
        description="Add two integers a and b and return the sum.",
        parameters={
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
            },
            "required": ["a", "b"],
        },
        label="Add",
        execute=execute,
    )


class EventRecorder:
    def __init__(self) -> None:
        self.types: list[str] = []
        self.events: list[AgentEvent] = []

    def __call__(self, event: AgentEvent, signal: Any) -> None:
        self.events.append(event)
        self.types.append(event["type"])
