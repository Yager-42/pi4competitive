"""C1 exit smoke: prompt → tool → JSONL → resume."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from earendil_works.pi_ai import create_models
from earendil_works.pi_ai.providers.faux import (
    faux_assistant_message,
    faux_provider,
    faux_text,
    faux_tool_call,
)

from earendil_works.pi_agent import Agent, AgentOptions, AgentTool
from earendil_works.pi_agent.harness.env.python_env import LocalFileSystem
from earendil_works.pi_agent.harness.session import DEFAULT_SESSIONS_DIR_NAME, JsonlSessionRepo


async def _echo(tool_call_id: str, params: dict[str, Any], signal=None, on_update=None) -> dict[str, Any]:
    return {"content": [faux_text(str(params.get("text", "")))], "details": {}}


@pytest.mark.asyncio
async def test_prompt_tool_jsonl_resume(tmp_path: Path) -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"](
        [
            faux_assistant_message([faux_tool_call("echo", {"text": "lens"})]),
            faux_assistant_message("done"),
        ]
    )
    model = faux["getModel"]()
    tool = AgentTool(
        name="echo",
        description="echo",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        label="Echo",
        execute=_echo,
    )

    sessions_root = tmp_path / DEFAULT_SESSIONS_DIR_NAME
    fs = LocalFileSystem(cwd=str(tmp_path))
    repo = JsonlSessionRepo({"fs": fs, "sessionsRoot": str(sessions_root)})
    session = await repo.create({"cwd": str(tmp_path)})

    agent = Agent(
        AgentOptions(
            stream_fn=models.streamSimple,
            initial_state={"model": model, "tools": [tool], "systemPrompt": "test"},
            tool_execution="sequential",
        )
    )
    await agent.prompt("use the tool")
    await agent.wait_for_idle()

    for msg in agent.state.messages:
        await session.append_message(msg)

    meta = await session.get_metadata()
    reopened = await repo.open(meta)
    ctx = await reopened.build_context()
    roles = [m.get("role") for m in ctx["messages"] if isinstance(m, dict)]
    assert "user" in roles
    assert "toolResult" in roles
    assert roles[-1] == "assistant"
    # on-disk file exists under data/sessions layout
    assert Path(meta["path"]).is_file()
    assert "sessions" in meta["path"]
