from __future__ import annotations

from functools import partial
from typing import Any

import pytest

from earendil_works.pi_agent import (
    AgentTool,
    DirectToolExecutor,
    ToolExecutionTarget,
    derive_tool_execution_target,
)
from earendil_works.pi_agent.types import AgentToolResult


async def _top_level_execute(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
) -> AgentToolResult:
    return {"content": [{"type": "text", "text": str(params["value"])}], "details": {}}


async def _context_execute(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
    context: Any = None,
) -> AgentToolResult:
    return {"content": [], "details": {}}


def _sync_execute(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
) -> AgentToolResult:
    return {"content": [], "details": {}}


def _nested_execute() -> Any:
    async def nested(
        tool_call_id: str,
        params: dict[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> AgentToolResult:
        return {"content": [], "details": {}}

    return nested


class _CallableObject:
    async def __call__(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> AgentToolResult:
        return {"content": [], "details": {}}


class _BoundCallable:
    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> AgentToolResult:
        return {"content": [], "details": {}}


def test_derives_importable_module_level_async_target() -> None:
    assert derive_tool_execution_target(_top_level_execute) == ToolExecutionTarget(
        module=__name__, qualname="_top_level_execute"
    )


def test_rejects_forged_callable_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_top_level_execute, "__module__", "math")
    assert derive_tool_execution_target(_top_level_execute) is None

def test_rejects_non_importable_or_context_aware_shapes() -> None:
    bound = _BoundCallable()
    assert derive_tool_execution_target(_nested_execute()) is None
    assert derive_tool_execution_target(_context_execute) is None
    assert derive_tool_execution_target(_sync_execute) is None
    assert derive_tool_execution_target(partial(_top_level_execute)) is None
    assert derive_tool_execution_target(bound.execute) is None
    assert derive_tool_execution_target(_CallableObject()) is None


@pytest.mark.asyncio
async def test_direct_executor_preserves_call_contract_and_ignores_scope() -> None:
    calls: list[tuple[Any, ...]] = []

    async def execute(
        tool_call_id: str,
        params: dict[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> AgentToolResult:
        calls.append((tool_call_id, params, signal, on_update))
        return {"content": [{"type": "text", "text": "ok"}], "details": {}}

    tool = AgentTool(
        name="direct",
        description="direct",
        parameters={"type": "object"},
        label="Direct",
        execute=execute,
    )
    update = lambda _partial: None
    result = await DirectToolExecutor().execute(
        scope_id="ignored",
        tool=tool,
        tool_call_id="call-1",
        params={"value": 1},
        signal="signal",
        on_update=update,
    )

    assert result["content"][0]["text"] == "ok"  # type: ignore[index]
    assert calls == [("call-1", {"value": 1}, "signal", update)]

@pytest.mark.asyncio
async def test_direct_executor_preserves_errors_updates_and_metadata() -> None:
    updates: list[AgentToolResult] = []

    async def execute(
        tool_call_id: str,
        params: dict[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> AgentToolResult:
        on_update({"details": {"step": 1}})
        return {
            "content": [],
            "details": {"ok": True},
            "addedToolNames": ["later"],
            "terminate": True,
        }

    tool = AgentTool(
        name="parity",
        description="parity",
        parameters={"type": "object"},
        label="Parity",
        execute=execute,
    )
    result = await DirectToolExecutor().execute(
        scope_id="scope",
        tool=tool,
        tool_call_id="call",
        params={},
        signal=None,
        on_update=updates.append,
    )
    assert updates == [{"details": {"step": 1}}]
    assert result["addedToolNames"] == ["later"]
    assert result["terminate"] is True

    async def fails(*args: Any) -> AgentToolResult:
        raise RuntimeError("direct failure")

    failing = AgentTool(
        name="fails",
        description="fails",
        parameters={"type": "object"},
        label="Fails",
        execute=fails,
    )
    with pytest.raises(RuntimeError, match="direct failure"):
        await DirectToolExecutor().execute(
            scope_id="scope",
            tool=failing,
            tool_call_id="call",
            params={},
            signal=None,
            on_update=updates.append,
        )
