from __future__ import annotations

from typing import Any

import pytest
from earendil_works.pi_ai import create_models
from earendil_works.pi_ai.providers.faux import faux_assistant_message, faux_provider, faux_text, faux_tool_call

from earendil_works.pi_agent import AgentLoopConfig, AgentTool, run_agent_loop
from earendil_works.pi_agent.types import AgentContext, AgentEvent, AgentMessage, AgentToolResult


def _convert_to_llm(messages: list[AgentMessage]) -> list[Any]:
    return [m for m in messages if isinstance(m, dict) and m.get("role") in ("user", "assistant", "toolResult")]


@pytest.mark.asyncio
async def test_executor_seam_receives_prepared_call_and_scope() -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"](
        [
            faux_assistant_message([faux_tool_call("remote", {"value": "input"})]),
            faux_assistant_message("done"),
        ]
    )
    model = faux["getModel"]()
    assert model is not None

    host_calls: list[str] = []

    async def host_execute(
        tool_call_id: str,
        params: dict[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> AgentToolResult:
        host_calls.append(tool_call_id)
        raise AssertionError("the injected executor must own execution")

    tool = AgentTool(
        name="remote",
        description="remote",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        label="Remote",
        execute=host_execute,
    )

    class SpyExecutor:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

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
            self.calls.append(
                {
                    "scope_id": scope_id,
                    "tool": tool,
                    "tool_call_id": tool_call_id,
                    "params": params,
                    "signal": signal,
                }
            )
            on_update({"content": [faux_text("partial")], "details": {"partial": True}})
            return {"content": [faux_text("remote-result")], "details": {"executor": "spy"}}

    spy = SpyExecutor()
    events: list[AgentEvent] = []
    context: AgentContext = {"systemPrompt": "test", "messages": [], "tools": [tool]}
    config = AgentLoopConfig(
        model=model,
        convertToLlm=_convert_to_llm,
        toolExecutor=spy,
        toolExecutionScopeId="scope-1",
        toolExecution="sequential",
    )

    messages = await run_agent_loop(
        [{"role": "user", "content": "run", "timestamp": 0}],
        context,
        config,
        events.append,
        None,
        models.streamSimple,
    )

    assert host_calls == []
    assert len(spy.calls) == 1
    assert spy.calls[0]["scope_id"] == "scope-1"
    assert spy.calls[0]["tool"] is tool
    assert spy.calls[0]["tool_call_id"]
    assert spy.calls[0]["params"] == {"value": "input"}
    updates = [event for event in events if event["type"] == "tool_execution_update"]
    assert len(updates) == 1
    tool_results = [message for message in messages if message.get("role") == "toolResult"]
    assert tool_results[0]["content"][0]["text"] == "remote-result"  # type: ignore[index]
