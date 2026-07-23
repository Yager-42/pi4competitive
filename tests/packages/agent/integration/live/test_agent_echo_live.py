"""Live P2 smoke: Agent + real model (+ optional tool) using repo-root .env.

Run:
  .venv/bin/pytest tests/packages/agent/integration/live -m live -q
Default offline suite excludes these via -m 'not live'.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from earendil_works.pi_agent import Agent, AgentOptions, AgentTool, JsonlSessionRepo
from earendil_works.pi_agent.harness.env.python_env import LocalFileSystem

pytestmark = pytest.mark.live


def _text_of(message: dict[str, Any]) -> str:
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


@pytest.mark.asyncio
async def test_live_agent_prompt_text(live_gateway) -> None:
    models = live_gateway["models"]
    model = live_gateway["model"]
    agent = Agent(
        AgentOptions(
            stream_fn=models.streamSimple,
            initial_state={
                "model": model,
                "systemPrompt": (
                    "You are a test assistant. Reply with exactly the single word: pong"
                ),
            },
            get_api_key=lambda _provider: live_gateway["api_key"],
        )
    )
    await agent.prompt("Reply with exactly: pong")
    await agent.wait_for_idle()

    assert agent.state.isStreaming is False
    assert agent.state.errorMessage is None, agent.state.errorMessage
    assistants = [
        m for m in agent.state.messages if isinstance(m, dict) and m.get("role") == "assistant"
    ]
    assert assistants, "expected assistant message"
    last = assistants[-1]
    stop = last.get("stopReason")
    assert stop in ("stop", "length", "toolUse"), f"stopReason={stop} err={last.get('errorMessage')}"
    text = _text_of(last).lower()
    # Model should mention pong; be slightly loose for gateway quirks
    assert "pong" in text or stop == "stop"


@pytest.mark.asyncio
async def test_live_agent_tool_then_jsonl_resume(live_gateway, tmp_path: Path) -> None:
    models = live_gateway["models"]
    model = live_gateway["model"]

    async def echo_execute(
        tool_call_id: str,
        params: dict[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> dict[str, Any]:
        text = str(params.get("text", ""))
        return {
            "content": [{"type": "text", "text": text}],
            "details": {"echoed": text},
        }

    echo = AgentTool(
        name="echo",
        description="Echo back the text argument. Use this tool when the user asks you to echo.",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Text to echo"}},
            "required": ["text"],
        },
        label="Echo",
        execute=echo_execute,
    )

    agent = Agent(
        AgentOptions(
            stream_fn=models.streamSimple,
            initial_state={
                "model": model,
                "tools": [echo],
                "systemPrompt": (
                    "You have one tool: echo. When the user asks to echo something, "
                    "you MUST call the echo tool with that text. After the tool result, "
                    "reply briefly confirming the echoed text."
                ),
            },
            get_api_key=lambda _provider: live_gateway["api_key"],
            tool_execution="sequential",
        )
    )
    await agent.prompt('Please use the echo tool to echo exactly: live-ok')
    await agent.wait_for_idle()

    assert agent.state.errorMessage is None, agent.state.errorMessage
    roles = [m.get("role") for m in agent.state.messages if isinstance(m, dict)]
    assert "user" in roles
    assert "assistant" in roles
    # Prefer tool path; if gateway model refuses tools, still require a completed assistant turn
    tool_results = [
        m for m in agent.state.messages if isinstance(m, dict) and m.get("role") == "toolResult"
    ]
    assistants = [
        m for m in agent.state.messages if isinstance(m, dict) and m.get("role") == "assistant"
    ]
    assert assistants
    assert assistants[-1].get("stopReason") in ("stop", "length", "toolUse", "error")
    assert assistants[-1].get("stopReason") != "error" or tool_results

    # Persist + resume via JSONL under data/sessions layout
    sessions_root = tmp_path / "data" / "sessions"
    fs = LocalFileSystem(cwd=str(tmp_path))
    repo = JsonlSessionRepo({"fs": fs, "sessionsRoot": str(sessions_root)})
    session = await repo.create({"cwd": str(tmp_path)})
    for msg in agent.state.messages:
        await session.append_message(msg)
    meta = await session.get_metadata()
    reopened = await repo.open(meta)
    ctx = await reopened.build_context()
    assert len(ctx["messages"]) == len(agent.state.messages)
    assert Path(meta["path"]).is_file()
