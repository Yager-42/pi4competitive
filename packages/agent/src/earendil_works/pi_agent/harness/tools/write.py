"""Write file tool.

upstream: packages/agent/src/harness/tools/write.ts
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from earendil_works.pi_agent.types import AgentTool, AgentToolResult


async def _write_execute(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
) -> AgentToolResult:
    path = Path(str(params.get("path") or ""))
    content = str(params.get("content") or "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {
        "content": [{"type": "text", "text": f"Wrote {len(content)} bytes to {path}"}],
        "details": {"path": str(path), "bytes": len(content)},
    }


def create_write_tool() -> AgentTool:
    return AgentTool(
        name="write",
        description="Write a UTF-8 text file",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        label="Write",
        execute=_write_execute,
        executionMode="sequential",
    )


__all__ = ["create_write_tool"]
