from __future__ import annotations

import asyncio
from typing import Any

import pytest
from earendil_works.pi_ai import create_models
from earendil_works.pi_ai.providers.faux import faux_assistant_message, faux_provider, faux_text, faux_tool_call

from earendil_works.pi_agent import AgentLoopConfig, AgentTool, run_agent_loop
from earendil_works.pi_agent.types import AgentContext, AgentEvent, AgentMessage, AgentToolResult


def _convert_to_llm(messages: list[AgentMessage]) -> list[Any]:
    return [m for m in messages if isinstance(m, dict) and m.get("role") in ("user", "assistant", "toolResult")]


def _tool(name: str) -> AgentTool:
    async def host_execute(
        tool_call_id: str,
        params: dict[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> AgentToolResult:
        raise AssertionError("the injected executor must own execution")

    return AgentTool(
        name=name,
        description=name,
        parameters={"type": "object"},
        label=name,
        execute=host_execute,
    )


class _ParallelExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0
        self.both_started = asyncio.Event()
        self.release = asyncio.Event()

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
        self.calls.append(tool.name)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if self.active == 2:
            self.both_started.set()
        await self.both_started.wait()
        await self.release.wait()
        self.active -= 1
        return {"content": [faux_text(tool.name)], "details": {"scope": scope_id}}


@pytest.mark.asyncio
async def test_parallel_executor_calls_overlap_and_results_keep_source_order() -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"](
        [
            faux_assistant_message(
                [
                    faux_tool_call("a", {}, id="call-a"),
                    faux_tool_call("b", {}, id="call-b"),
                ]
            ),
            faux_assistant_message("done"),
        ]
    )
    model = faux["getModel"]()
    assert model is not None
    executor = _ParallelExecutor()
    trace: list[str] = []

    async def before(context, signal=None):  # type: ignore[no-untyped-def]
        trace.append(f"before:{context['toolCall']['name']}")

    async def after(context, signal=None):  # type: ignore[no-untyped-def]
        trace.append(f"after:{context['toolCall']['name']}")

    async def emit(event: AgentEvent) -> None:
        if event["type"] in {"tool_execution_start", "tool_execution_end"}:
            trace.append(f"{event['type']}:{event['toolCallId']}")

    context: AgentContext = {
        "systemPrompt": "test",
        "messages": [],
        "tools": [_tool("a"), _tool("b")],
    }
    config = AgentLoopConfig(
        model=model,
        convertToLlm=_convert_to_llm,
        toolExecutor=executor,
        toolExecutionScopeId="parallel-scope",
        beforeToolCall=before,
        afterToolCall=after,
    )
    task = asyncio.create_task(
        run_agent_loop(
            [{"role": "user", "content": "run", "timestamp": 0}],
            context,
            config,
            emit,
            None,
            models.streamSimple,
        )
    )
    await executor.both_started.wait()
    assert executor.max_active == 2
    executor.release.set()
    messages = await task

    assert executor.calls == ["a", "b"]
    results = [message for message in messages if message.get("role") == "toolResult"]
    assert [message["toolName"] for message in results] == ["a", "b"]
    for name, call_id in (("a", "call-a"), ("b", "call-b")):
        assert trace.index(f"tool_execution_start:{call_id}") < trace.index(f"before:{name}")
        assert trace.index(f"before:{name}") < trace.index(f"after:{name}")
        assert trace.index(f"after:{name}") < trace.index(f"tool_execution_end:{call_id}")
