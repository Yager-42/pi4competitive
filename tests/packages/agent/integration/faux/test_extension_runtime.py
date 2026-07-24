from __future__ import annotations

from typing import Any

import pytest
from earendil_works.pi_ai import create_models
from earendil_works.pi_ai.providers.faux import (
    faux_assistant_message,
    faux_provider,
    faux_text,
    faux_tool_call,
)
from earendil_works.pi_agent import (
    Agent,
    AgentHarness,
    AgentOptions,
    AgentTool,
    JsonlSessionRepo,
    attach_extension_runtime,
    create_extension_runtime,
    load_extension_from_factory,
    load_capability_packages,
)
from earendil_works.pi_agent.harness.env.python_env import LocalFileSystem


async def _echo(_id: str, params: dict[str, Any], _signal=None, on_update=None):
    if on_update:
        on_update({"content": [faux_text("partial")], "details": {}})
    return {"content": [faux_text(params["text"])], "details": {}}


@pytest.mark.asyncio
async def test_agent_emits_engine_lifecycle_and_mutation_hooks(tmp_path) -> None:
    seen: list[str] = []
    payloads: list[dict[str, Any]] = []

    def factory(api) -> None:
        api.registerTool(AgentTool(
            name="echo", label="Echo", description="echo",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            execute=_echo,
        ))
        for event in (
            "session_start", "context", "before_provider_headers", "after_provider_response",
            "agent_start", "agent_end", "agent_settled", "turn_start", "turn_end",
            "message_start", "message_update", "message_end", "tool_execution_start",
            "tool_execution_update", "tool_execution_end", "tool_call", "tool_result",
        ):
            api.on(event, lambda incoming, _ctx, event=event: seen.append(event))
        api.on("before_agent_start", lambda incoming, _ctx: {
            "systemPrompt": incoming["systemPrompt"] + " EXTENSION_MARKER"
        })
        api.on("before_provider_request", lambda incoming, _ctx: {
            **incoming["payload"], "extensionMarker": True
        })
        api.on("before_provider_request", lambda incoming, _ctx: payloads.append(incoming["payload"]))

    runtime = create_extension_runtime()
    extension = await load_extension_from_factory(factory, tmp_path, runtime)
    loaded = type("Loaded", (), {"extensions": [extension], "runtime": runtime})()

    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"]([
        faux_assistant_message([faux_tool_call("echo", {"text": "ok"})]),
        faux_assistant_message("done"),
    ])
    model = faux["getModel"]()
    assert model is not None
    async def stream_with_payload(request_model, context, options):
        callback = options.get("onPayload")
        if callback:
            await callback({"messages": context["messages"]}, request_model)
        return models.streamSimple(request_model, context, options)

    agent = Agent(AgentOptions(
        stream_fn=stream_with_payload,
        initial_state={"model": model, "systemPrompt": "base", "tools": []},
        tool_execution="sequential",
    ))
    attach_extension_runtime(agent, loaded, str(tmp_path))
    await agent.prompt("use echo")

    assert payloads and payloads[0]["extensionMarker"] is True
    required = {
        "session_start", "context", "before_provider_headers", "after_provider_response",
        "agent_start", "agent_end", "agent_settled", "turn_start", "turn_end",
        "message_start", "message_end", "tool_execution_start", "tool_execution_update",
        "tool_execution_end", "tool_call", "tool_result",
    }
    assert required <= set(seen)
    assert not hasattr(AgentOptions(), "transform_context")
    assert not hasattr(AgentOptions(), "on_payload")


@pytest.mark.asyncio
async def test_harness_and_selection_events(tmp_path) -> None:
    seen: list[str] = []

    def factory(api) -> None:
        for event in (
            "session_info_changed", "session_before_compact", "session_compact",
            "session_shutdown", "model_select", "thinking_level_select",
        ):
            api.on(event, lambda _incoming, _ctx, event=event: seen.append(event))
        api.on("session_before_compact", lambda *_: {"compaction": {"summary": "from extension"}})

    runtime = create_extension_runtime()
    extension = await load_extension_from_factory(factory, tmp_path, runtime)
    loaded = type("Loaded", (), {"extensions": [extension], "runtime": runtime})()
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    model = faux["getModel"]()
    fs = LocalFileSystem(cwd=str(tmp_path))
    repo = JsonlSessionRepo({"fs": fs, "sessionsRoot": str(tmp_path / "sessions")})
    session = await repo.create({"cwd": str(tmp_path)})
    harness = AgentHarness(session=session, stream_fn=models.streamSimple, model=model)
    attach_extension_runtime(harness.agent, loaded, str(tmp_path))

    await harness.session_info_changed("named")
    await harness.agent.set_model(model)
    await harness.agent.set_thinking_level("low")
    assert await harness.compact() == {"summary": "from extension"}
    await harness.shutdown()
    assert {"session_info_changed", "session_before_compact", "session_compact",
            "session_shutdown", "model_select", "thinking_level_select"} <= set(seen)


@pytest.mark.asyncio
async def test_capability_resources_apply_to_harness(tmp_path) -> None:
    root = tmp_path / "capability_packages"
    package = root / "resources"
    (package / "extensions").mkdir(parents=True)
    (package / "skills").mkdir()
    (package / "prompts").mkdir()
    (package / "extensions" / "empty.py").write_text("def register(api):\n    pass\n")
    (package / "skills" / "SKILL.md").write_text(
        "---\nname: concise\ndescription: Be concise\n---\nUse short answers.\n"
    )
    (package / "prompts" / "review.md").write_text("Review $ARGUMENTS")
    report = await load_capability_packages(root=root)

    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    fs = LocalFileSystem(cwd=str(tmp_path))
    repo = JsonlSessionRepo({"fs": fs, "sessionsRoot": str(tmp_path / "sessions")})
    session = await repo.create({"cwd": str(tmp_path)})
    harness = AgentHarness(
        session=session, stream_fn=models.streamSimple, model=faux["getModel"],
        capability_report=report,
    )
    assert "concise" in harness.agent.state.systemPrompt
    assert [prompt.name for prompt in harness.prompts] == ["review"]
    await harness.shutdown()
