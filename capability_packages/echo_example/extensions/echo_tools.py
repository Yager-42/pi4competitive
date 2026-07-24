"""Example capability package: echo tool.

Discovered via capability_packages/echo_example (local package-manager subset).
"""
from __future__ import annotations

from typing import Any

from earendil_works.pi_agent.types import AgentTool, AgentToolResult


async def _echo_execute(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
) -> AgentToolResult:
    text = str(params.get("text", ""))
    return {
        "content": [{"type": "text", "text": text}],
        "details": {"echoed": text, "package": "echo_example"},
    }


def register(api: Any) -> None:
    api.registerTool(AgentTool(
        name="echo",
        description="Echo text back (capability_packages/echo_example)",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to echo"},
            },
            "required": ["text"],
        },
        label="Echo",
        execute=_echo_execute,
        executionMode="parallel",
    ))
