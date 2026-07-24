"""P3.1 live extension runtime gate. Never logs secrets."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from earendil_works.pi_agent import (
    Agent,
    AgentOptions,
    attach_extension_runtime,
    load_extensions,
)
from tests.packages.agent.integration.live.helpers import text_of, tool_results

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_live_extension_load_hooks_and_tool_call(live_gateway, tmp_path: Path) -> None:
    payload_probe = tmp_path / "payload-hook-fired"
    extension = tmp_path / "live_extension.py"
    extension.write_text(
        f'''from earendil_works.pi_agent import AgentTool

async def execute(_id, params, signal=None, on_update=None):
    text = str(params.get("text", ""))
    return {{"content": [{{"type": "text", "text": text}}], "details": {{"live": True}}}}

def register(api):
    api.registerTool(AgentTool(
        name="live_extension_echo", label="Live extension echo",
        description="Echo text. Always use when explicitly requested.",
        parameters={{"type": "object", "properties": {{"text": {{"type": "string"}}}}, "required": ["text"]}},
        execute=execute,
    ))
    api.on("before_agent_start", lambda event, ctx: {{
        "systemPrompt": event["systemPrompt"] + "\\nLIVE_SYSTEM_HOOK"
    }})
    def payload(event, ctx):
        from pathlib import Path
        Path({str(payload_probe)!r}).write_text("fired")
        return {{**event["payload"], "user": "pi-extension-live"}}
    api.on("before_provider_request", payload)
''',
        encoding="utf-8",
    )

    loaded = await load_extensions([extension], tmp_path)
    assert not loaded.errors
    agent_contexts: list[str] = []

    def stream_with_probe(model, context, options):
        agent_contexts.append(str(context.get("systemPrompt") or ""))
        return live_gateway["models"].streamSimple(model, context, options)

    agent = Agent(AgentOptions(
        stream_fn=stream_with_probe,
        initial_state={
            "model": live_gateway["model"],
            "systemPrompt": (
                "You MUST call live_extension_echo exactly once with text live-extension-ok. "
                "Do not answer without calling the tool."
            ),
            "tools": [],
        },
        get_api_key=lambda _provider: live_gateway["api_key"],
        tool_execution="sequential",
    ))
    runner = attach_extension_runtime(agent, loaded, str(tmp_path))
    assert [tool.definition.name for tool in runner.get_all_registered_tools()] == ["live_extension_echo"]

    await agent.prompt("Call live_extension_echo with text exactly live-extension-ok")
    results = tool_results(agent.state.messages)
    assert results, "real model did not issue the required extension tool call"
    assert any(result.get("toolName") == "live_extension_echo" for result in results)
    assert "live-extension-ok" in " ".join(text_of(result) for result in results)
    assert any("LIVE_SYSTEM_HOOK" in prompt for prompt in agent_contexts)
    assert payload_probe.read_text() == "fired"
