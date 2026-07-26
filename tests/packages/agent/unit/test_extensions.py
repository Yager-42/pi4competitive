from __future__ import annotations

from typing import Any

import pytest

from earendil_works.pi_agent.extensions import (
    CompactionPlan,
    ExtensionRunner,
    ExtensionAPI,
    create_extension_runtime,
    load_extension_from_factory,
    load_extensions,
    wrap_registered_tools,
)
from earendil_works.pi_agent.types import AgentTool


async def _execute(_id: str, params: dict[str, Any], *_: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": params["text"]}], "details": {}}


def _tool() -> AgentTool:
    return AgentTool(
        name="echo",
        label="Echo",
        description="echo",
        parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        execute=_execute,
    )


def test_compaction_plan_public_shape() -> None:
    plan: CompactionPlan = {
        "version": 1, "snapshotFingerprint": "sha256:x", "foldEntryIds": ["a"],
        "retainEntryIds": ["b"], "summaryInstructions": "summarize", "details": {},
    }
    assert plan["version"] == 1


@pytest.mark.asyncio
async def test_loader_runner_and_wrapper_contract(tmp_path) -> None:
    runtime = create_extension_runtime()

    async def factory(api) -> None:
        api.registerTool(_tool())
        api.on("before_agent_start", lambda event, _ctx: {"systemPrompt": event["systemPrompt"] + " one"})
        api.on("before_agent_start", lambda event, _ctx: {"systemPrompt": event["systemPrompt"] + " two"})

    extension = await load_extension_from_factory(factory, tmp_path, runtime)
    assert not hasattr(extension, "ui")
    assert not hasattr(ExtensionAPI, "add_tool")
    with pytest.raises(RuntimeError, match="not initialized"):
        runtime.call("sendMessage", {})
    runner = ExtensionRunner([extension], runtime, tmp_path)
    result = await runner.emit_before_agent_start("hi", None, "base", {})
    assert result == {"messages": None, "systemPrompt": "base one two"}

    tools = wrap_registered_tools(runner.get_all_registered_tools(), runner)
    assert (await tools[0].execute("1", {"text": "ok"}, None, None))["content"][0]["text"] == "ok"

    with pytest.raises(RuntimeError, match="not bound"):
        runner.create_context().getSystemPrompt()
    runner.invalidate("stale")
    with pytest.raises(RuntimeError, match="stale"):
        runner.create_context()


@pytest.mark.asyncio
async def test_event_boundaries_errors_and_merges(tmp_path) -> None:
    errors = []
    calls = []
    runtime = create_extension_runtime()

    def factory(api) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            api.on("input", lambda *_: None)
        api.on("tool_call", lambda *_: {"block": False})
        api.on("tool_call", lambda *_: {"block": True, "reason": "no"})
        api.on("tool_call", lambda *_: calls.append("unreachable"))
        api.on("message_end", lambda *_: {"message": {"role": "user", "content": []}})
        api.on("agent_start", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))

    extension = await load_extension_from_factory(factory, tmp_path, runtime)
    runner = ExtensionRunner([extension], runtime, tmp_path)
    runner.on_error(errors.append)
    assert await runner.emit_tool_call({"type": "tool_call", "toolCallId": "1", "toolName": "echo", "input": {}}) == {"block": True, "reason": "no"}
    assert calls == []
    assert await runner.emit_message_end({"type": "message_end", "message": {"role": "assistant", "content": []}}) is None
    await runner.emit({"type": "agent_start"})
    assert [error.event for error in errors] == ["message_end", "agent_start"]

    collision_runtime = create_extension_runtime()

    def collision_factory(api) -> None:
        api.on("session_before_compact", lambda *_: {"compactionPlan": {"version": 1}})
        api.on("session_before_compact", lambda *_: {"compactionPlan": {"version": 1}})

    collision_ext = await load_extension_from_factory(collision_factory, tmp_path, collision_runtime)
    collision_runner = ExtensionRunner([collision_ext], collision_runtime, tmp_path)
    collision_errors = []
    collision_runner.on_error(collision_errors.append)
    assert await collision_runner.emit({"type": "session_before_compact"}) == {"compactionCollision": True}
    assert collision_errors[0].event == "session_before_compact"

    bad = await load_extensions([tmp_path / "missing.py", tmp_path / "bad.txt"], tmp_path)
    assert len(bad.errors) == 2

    (tmp_path / "throws.py").write_text(
        "def register(api):\n    raise RuntimeError('register boom')\n", encoding="utf-8"
    )
    (tmp_path / "empty.py").write_text("# empty extension\n", encoding="utf-8")
    boundaries = await load_extensions([tmp_path / "throws.py", tmp_path / "empty.py"], tmp_path)
    assert len(boundaries.errors) == 1
    assert "register boom" in boundaries.errors[0]["error"]
    assert len(boundaries.extensions) == 1
