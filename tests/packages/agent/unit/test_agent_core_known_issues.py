from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest
from earendil_works.pi_ai import create_models
from earendil_works.pi_ai.providers.faux import faux_assistant_message, faux_provider, faux_tool_call

from earendil_works.pi_agent import (
    Agent,
    AgentLoopConfig,
    AgentOptions,
    AgentTool,
    ExtensionRunner,
    agent_loop,
    create_extension_runtime,
    load_extensions,
    run_agent_loop,
    wrap_registered_tools,
)
from earendil_works.pi_agent.types import AgentContext, AgentMessage, AgentToolResult


def _convert(messages: list[AgentMessage]) -> list[Any]:
    return list(messages)


def _tool(name: str) -> AgentTool:
    async def execute(_id: str, _params: dict[str, Any], signal: Any = None, _update: Any = None) -> AgentToolResult:
        if name == "first" and signal is not None:
            signal.aborted = True
        return {"content": [{"type": "text", "text": name}], "details": {}}

    return AgentTool(
        name=name,
        description=name,
        parameters={"type": "object", "properties": {}},
        label=name,
        execute=execute,
    )


def _faux_batch(tool_calls: list[dict[str, Any]]) -> tuple[Any, Any]:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"]([faux_assistant_message(tool_calls)])
    return models, faux["getModel"]()


@pytest.mark.asyncio
async def test_settled_dispatch_failure_still_finishes_agent() -> None:
    runtime = create_extension_runtime()
    runner = ExtensionRunner([], runtime, ".")
    agent = Agent(AgentOptions(extension_runner=runner))
    runtime.invalidate("stale")

    async def executor(_signal: Any) -> None:
        return None

    with pytest.raises(RuntimeError, match="stale"):
        await agent._run_with_lifecycle(executor)
    assert agent.signal is None
    assert agent.state.isStreaming is False
    await agent.wait_for_idle()


@pytest.mark.asyncio
async def test_reset_rejected_while_run_is_active() -> None:
    agent = Agent()
    gate = asyncio.Event()

    async def executor(_signal: Any) -> None:
        await gate.wait()

    task = asyncio.create_task(agent._run_with_lifecycle(executor))
    await asyncio.sleep(0)
    original = {"role": "user", "content": "keep", "timestamp": 0}
    agent.state.messages = [original]
    agent.steer({"role": "user", "content": "queued", "timestamp": 1})

    with pytest.raises(RuntimeError, match="reset"):
        agent.reset()
    assert agent.state.messages == [original]
    assert agent.has_queued_messages() is True
    assert agent.state.isStreaming is True

    gate.set()
    await task


@pytest.mark.asyncio
async def test_sequential_abort_synthesizes_remaining_tool_results() -> None:
    models, model = _faux_batch(
        [faux_tool_call("first", {}, id="first"), faux_tool_call("second", {}, id="second")]
    )
    signal = type("Signal", (), {"aborted": False})()
    context: AgentContext = {"systemPrompt": "", "messages": [], "tools": [_tool("first"), _tool("second")]}
    config = AgentLoopConfig(
        model=cast(Any, model),
        convertToLlm=_convert,
        toolExecution="sequential",
        shouldStopAfterTurn=lambda _ctx: True,
    )
    events: list[dict[str, Any]] = []
    messages = await run_agent_loop(
        [{"role": "user", "content": "run", "timestamp": 0}],
        context,
        config,
        events.append,
        signal,
        models.streamSimple,
    )
    results = [m for m in messages if m.get("role") == "toolResult"]
    assert [m["toolCallId"] for m in results] == ["first", "second"]
    assert all(m["isError"] is True or m["toolCallId"] == "first" for m in results)
    ends = [e["toolCallId"] for e in events if e["type"] == "tool_execution_end"]
    assert ends == ["first", "second"]


@pytest.mark.asyncio
async def test_parallel_abort_during_preparation_synthesizes_full_batch() -> None:
    models, model = _faux_batch(
        [faux_tool_call("first", {}, id="first"), faux_tool_call("second", {}, id="second")]
    )
    signal = type("Signal", (), {"aborted": False})()

    async def abort_before(_context: Any, _signal: Any) -> None:
        signal.aborted = True

    context: AgentContext = {"systemPrompt": "", "messages": [], "tools": [_tool("first"), _tool("second")]}
    config = AgentLoopConfig(
        model=cast(Any, model),
        convertToLlm=_convert,
        toolExecution="parallel",
        beforeToolCall=abort_before,
        shouldStopAfterTurn=lambda _ctx: True,
    )
    events: list[dict[str, Any]] = []
    messages = await run_agent_loop(
        [{"role": "user", "content": "run", "timestamp": 0}],
        context,
        config,
        events.append,
        signal,
        models.streamSimple,
    )
    results = [m for m in messages if m.get("role") == "toolResult"]
    assert [m["toolCallId"] for m in results] == ["first", "second"]
    assert all(m["isError"] for m in results)
    ends = [e["toolCallId"] for e in events if e["type"] == "tool_execution_end"]
    assert ends == ["first", "second"]


@pytest.mark.asyncio
async def test_agent_loop_stream_failure_completes_with_exception() -> None:
    config = AgentLoopConfig(model=cast(Any, {}), convertToLlm=_convert)
    stream = agent_loop(
        [{"role": "user", "content": "x", "timestamp": 0}],
        {"systemPrompt": "", "messages": []},
        config,
        None,
        None,
    )
    with pytest.raises(ValueError, match="stream_fn is required"):
        await asyncio.wait_for(stream.await_result(), timeout=1)
    assert stream._done is True


@pytest.mark.asyncio
async def test_loader_uses_resolved_source_metadata_and_wrapper_package_target(tmp_path: Path) -> None:
    package = tmp_path / "capability_packages"
    package.mkdir()
    extension_path = package / "echo.py"
    extension_path.write_text(
        "from earendil_works.pi_agent import AgentTool\n"
        "async def execute(_id, _params, _signal=None, _update=None):\n"
        "    return {'content': [], 'details': {}}\n"
        "def register(api):\n"
        "    api.registerTool(AgentTool(name='echo', description='echo', parameters={'type': 'object'}, label='Echo', execute=execute))\n",
        encoding="utf-8",
    )

    loaded = await load_extensions(["capability_packages/echo.py"], tmp_path)
    assert not loaded.errors
    extension = loaded.extensions[0]
    assert extension.path == "capability_packages/echo.py"
    registered = extension.tools["echo"]
    assert registered.sourceInfo.path == str(extension_path.resolve())
    assert registered.sourceInfo.baseDir == str(package.resolve())

    runner = ExtensionRunner(loaded.extensions, loaded.runtime, tmp_path)
    wrapped = wrap_registered_tools(runner.get_all_registered_tools(), runner)[0]
    assert wrapped.executionTarget is not None
    assert wrapped.executionTarget.module == "capability_packages.echo"


class _CustomAwaitable:
    def __init__(self, value: Any) -> None:
        self.value = value

    def __await__(self):
        async def resolve() -> Any:
            return self.value

        return resolve().__await__()


@pytest.mark.asyncio
async def test_extension_handlers_await_tasks_futures_and_custom_awaitables() -> None:
    runtime = create_extension_runtime()
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    future.set_result({"step": "future"})

    async def factory(api: Any) -> None:
        api.on("before_provider_request", lambda _event, _ctx: future)
        api.on("before_provider_request", lambda _event, _ctx: asyncio.create_task(_value("task")))
        api.on("before_provider_request", lambda _event, _ctx: _CustomAwaitable({"step": "custom"}))

    async def _value(step: str) -> dict[str, str]:
        return {"step": step}

    from earendil_works.pi_agent.extensions import load_extension_from_factory

    extension = await load_extension_from_factory(factory, ".", runtime)
    runner = ExtensionRunner([extension], runtime, ".")
    assert await runner.emit_before_provider_request({"step": "start"}) == {"step": "custom"}


@pytest.mark.asyncio
async def test_error_listener_failures_are_isolated() -> None:
    runtime = create_extension_runtime()

    async def factory(api: Any) -> None:
        async def fail(_event: Any, _ctx: Any) -> None:
            raise RuntimeError("handler")

        api.on("agent_start", fail)

    from earendil_works.pi_agent.extensions import load_extension_from_factory

    extension = await load_extension_from_factory(factory, ".", runtime)
    runner = ExtensionRunner([extension], runtime, ".")
    seen: list[str] = []

    def broken(_error: Any) -> None:
        raise RuntimeError("listener")

    runner.on_error(broken)
    runner.on_error(lambda error: seen.append(error.error))
    await runner.emit({"type": "agent_start"})
    assert seen == ["handler"]
