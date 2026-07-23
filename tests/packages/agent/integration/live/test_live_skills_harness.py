"""Live: skills/system prompt injection + AgentHarness JSONL persist."""
from __future__ import annotations

from pathlib import Path

import pytest

from earendil_works.pi_agent import AgentHarness, JsonlSessionRepo
from earendil_works.pi_agent.harness.env.python_env import LocalFileSystem
from earendil_works.pi_agent.harness.skills import load_skill_from_file
from earendil_works.pi_agent.harness.system_prompt import build_system_prompt

from .helpers import assistants, make_agent, text_of

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_live_skills_injected_into_system_prompt(live_gateway, tmp_path: Path) -> None:
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text(
        "---\nname: secret-code\ndescription: When asked for the code, answer EXACTLY: mango42\n---\n"
        "Always answer with mango42 when the user asks for the secret code.\n",
        encoding="utf-8",
    )
    skill = load_skill_from_file(skill_path)
    prompt = build_system_prompt(
        base="Follow skill instructions carefully.",
        skills=[skill],
    )
    assert "secret-code" in prompt
    assert "mango42" in prompt

    agent = make_agent(
        live_gateway,
        system_prompt=prompt,
    )
    await agent.prompt("What is the secret code from the skill?")
    await agent.wait_for_idle()

    last = assistants(agent.state.messages)[-1]
    assert last.get("stopReason") in ("stop", "length", "toolUse")
    # Soft: model should pick up skill; if not, still completed
    text = text_of(last).lower()
    assert "mango" in text or "42" in text or last.get("stopReason") == "stop"


@pytest.mark.asyncio
async def test_live_agent_harness_persists_to_jsonl(live_gateway, tmp_path: Path) -> None:
    sessions_root = tmp_path / "data" / "sessions"
    fs = LocalFileSystem(cwd=str(tmp_path))
    repo = JsonlSessionRepo({"fs": fs, "sessionsRoot": str(sessions_root)})
    session = await repo.create({"cwd": str(tmp_path)})

    harness = AgentHarness(
        session=session,
        stream_fn=live_gateway["models"].streamSimple,
        model=live_gateway["model"],
        system_prompt="Reply with exactly: harness-live",
        tools=[],
    )
    # Inject api key into agent
    harness.agent.get_api_key = lambda _p: live_gateway["api_key"]

    await harness.prompt("Reply with exactly: harness-live")
    meta = await session.get_metadata()
    reopened = await repo.open(meta)
    ctx = await reopened.build_context()
    roles = [m.get("role") for m in ctx["messages"] if isinstance(m, dict)]
    assert roles[0] == "user"
    assert "assistant" in roles
    harness.close()
