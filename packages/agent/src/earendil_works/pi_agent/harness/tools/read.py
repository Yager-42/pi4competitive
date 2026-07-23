"""Read file tool.

upstream: packages/agent/src/harness/tools/read.ts
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from earendil_works.pi_agent.types import AgentTool, AgentToolResult


async def _read_execute(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
) -> AgentToolResult:
    path = Path(str(params.get("path") or ""))
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    text = path.read_text(encoding="utf-8")
    return {"content": [{"type": "text", "text": text}], "details": {"path": str(path), "bytes": len(text)}}


def create_read_tool() -> AgentTool:
    return AgentTool(
        name="read",
        description="Read a UTF-8 text file",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path"}},
            "required": ["path"],
        },
        label="Read",
        execute=_read_execute,
        executionMode="parallel",
    )


__all__ = ["create_read_tool"]
