from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from earendil_works.pi_ai import create_models
from earendil_works.pi_ai.providers.faux import faux_assistant_message, faux_provider, faux_text, faux_tool_call

from earendil_works.pi_agent import Agent, AgentHarness, AgentOptions, AgentTool
from earendil_works.pi_agent.harness.env.python_env import LocalFileSystem
from earendil_works.pi_agent.harness.session.jsonl_repo import JsonlSessionRepo
from earendil_works.pi_agent.types import AgentToolResult


async def _host_execute(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
) -> AgentToolResult:
    raise AssertionError("the injected executor must own execution")


def _tool(name: str = "propagate") -> AgentTool:
    return AgentTool(
        name=name,
        description=name,
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        label=name,
        execute=_host_execute,
    )


class _Executor:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    async def execute(
        self,
        *,
        scope_id: str,
        tool: AgentTool,
        tool_call_id: str,
        params: Any,
        signal: Any | None,
        on_update,
    ) -> AgentToolResult:
        self.scopes.append(scope_id)
        return {"content": [faux_text(str(params["value"]))], "details": {"scope": scope_id}}


@pytest.mark.asyncio
async def test_agent_options_propagate_executor_and_scope() -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"](
        [
            faux_assistant_message([faux_tool_call("propagate", {"value": "agent"})]),
            faux_assistant_message("done"),
        ]
    )
    model = faux["getModel"]()
    assert model is not None
    executor = _Executor()
    agent = Agent(
        AgentOptions(
            stream_fn=models.streamSimple,
            initial_state={"model": model, "tools": [_tool()], "systemPrompt": "test"},
            tool_execution="sequential",
            tool_executor=executor,
            tool_execution_scope_id="agent-scope",
        )
    )

    await agent.prompt("run")

    assert executor.scopes == ["agent-scope"]


@pytest.mark.asyncio
async def test_harness_resume_reuses_injected_scope(tmp_path: Path) -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"](
        [
            faux_assistant_message([faux_tool_call("propagate", {"value": "first"})]),
            faux_assistant_message("done"),
            faux_assistant_message([faux_tool_call("propagate", {"value": "second"})]),
            faux_assistant_message("done"),
        ]
    )
    model = faux["getModel"]()
    assert model is not None
    repo = JsonlSessionRepo(
        {"fs": LocalFileSystem(cwd=str(tmp_path)), "sessionsRoot": str(tmp_path / "sessions")}
    )
    session = await repo.create({"cwd": str(tmp_path)})
    executor = _Executor()
    harness = AgentHarness(
        session=session,
        stream_fn=models.streamSimple,
        model=model,
        tools=[_tool()],
        tool_execution="sequential",
        tool_executor=executor,
        tool_execution_scope_id="resume-scope",
    )

    await harness.prompt("first")
    metadata = await session.get_metadata()
    harness.close()

    resumed_session = await repo.open(metadata)
    resumed = AgentHarness(
        session=resumed_session,
        stream_fn=models.streamSimple,
        model=model,
        tools=[_tool()],
        tool_execution="sequential",
        tool_executor=executor,
        tool_execution_scope_id="resume-scope",
    )
    await resumed.prompt("second")
    resumed.close()

    assert executor.scopes == ["resume-scope", "resume-scope"]

@pytest.mark.asyncio
async def test_dynamic_agent_tools_reuse_injected_executor() -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"](
        [
            faux_assistant_message([faux_tool_call("first", {"value": "one"})]),
            faux_assistant_message("done"),
            faux_assistant_message([faux_tool_call("second", {"value": "two"})]),
            faux_assistant_message("done"),
        ]
    )
    model = faux["getModel"]()
    assert model is not None
    executor = _Executor()
    agent = Agent(
        AgentOptions(
            stream_fn=models.streamSimple,
            initial_state={"model": model, "tools": [_tool("first")]},
            tool_execution="sequential",
            tool_executor=executor,
            tool_execution_scope_id="dynamic-scope",
        )
    )

    await agent.prompt("first")
    agent.state.tools = [_tool("second")]
    await agent.prompt("second")

    assert executor.scopes == ["dynamic-scope", "dynamic-scope"]
