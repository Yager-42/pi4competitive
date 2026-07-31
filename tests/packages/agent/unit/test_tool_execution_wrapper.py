from __future__ import annotations

from typing import Any

import pytest

from earendil_works.pi_agent import AgentTool, ToolExecutionTarget
from earendil_works.pi_agent.extensions import (
    ExtensionRunner,
    create_extension_runtime,
    load_extension_from_factory,
    wrap_registered_tools,
)


async def _wrapped_execute(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": str(params["value"])}], "details": {}}


def _tool() -> AgentTool:
    return AgentTool(
        name="wrapped",
        label="Wrapped",
        description="wrapped",
        parameters={"type": "object", "properties": {"value": {"type": "string"}}},
        execute=_wrapped_execute,
    )


@pytest.mark.asyncio
async def test_extension_wrapper_preserves_target_and_callable_lineage(tmp_path) -> None:
    runtime = create_extension_runtime()

    async def factory(api) -> None:
        api.registerTool(_tool())

    extension = await load_extension_from_factory(factory, tmp_path, runtime)
    runner = ExtensionRunner([extension], runtime, tmp_path)
    wrapped = wrap_registered_tools(runner.get_all_registered_tools(), runner)[0]

    assert wrapped.executionTarget == ToolExecutionTarget(__name__, "_wrapped_execute")
    assert getattr(wrapped.execute, "__wrapped__", None) is _wrapped_execute
    result = await wrapped.execute("call-1", {"value": "ok"}, None, None)
    assert result["content"][0]["text"] == "ok"  # type: ignore[index]
