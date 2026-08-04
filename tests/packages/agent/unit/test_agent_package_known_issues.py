from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from earendil_works.pi_agent import AgentTool
from earendil_works.pi_agent.package_manager.resource_loader import materialize_resolved_async
from earendil_works.pi_agent.package_manager.types import (
    LoadReport,
    PathMetadata,
    ResolvedPaths,
    ResolvedResource,
)
from earendil_works.pi_agent.types import AgentLoopConfig


def _tool(name: str) -> AgentTool:
    async def execute(tool_call_id, params, signal=None, on_update=None):
        return {"content": [], "details": {}}

    return AgentTool(
        name=name,
        description=name,
        parameters={"type": "object"},
        label=name,
        execute=execute,
    )


def test_apply_capability_report_assigns_merged_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    apply_module = __import__(
        "earendil_works.pi_agent.package_manager.apply", fromlist=["apply_capability_report"]
    )
    monkeypatch.setattr(apply_module, "attach_extension_runtime", lambda *args, **kwargs: None)
    monkeypatch.setattr(apply_module, "build_system_prompt", lambda **kwargs: kwargs["base"])
    state = SimpleNamespace(tools=[_tool("existing")], systemPrompt="base")
    agent = SimpleNamespace(state=state, skills=[], prompts=[])
    report = LoadReport(
        root=Path("."),
        resolved=ResolvedPaths(),
        tools=[_tool("incoming")],
        extension_result=object(),
    )

    apply_module.apply_capability_report(agent, report)

    assert [tool.name for tool in agent.state.tools] == ["existing", "incoming"]


@pytest.mark.asyncio
async def test_prompt_package_association_skips_failed_prompt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    loader = __import__(
        "earendil_works.pi_agent.package_manager.resource_loader", fromlist=["materialize_resolved_async"]
    )

    class Result:
        extensions: list[object] = []
        errors: list[dict[str, str]] = []

    class Runner:
        @classmethod
        def from_load_result(cls, result, root):
            return cls()

        def get_all_registered_tools(self):
            return []

    async def load_extensions(paths, root):
        return Result()

    monkeypatch.setattr(loader, "load_extensions", load_extensions)
    monkeypatch.setattr(loader, "ExtensionRunner", Runner)
    monkeypatch.setattr(loader, "wrap_registered_tools", lambda tools, runner: tools)

    good = tmp_path / "good.md"
    good.write_text("---\nname: good\n---\nbody\n", encoding="utf-8")
    missing = tmp_path / "missing.md"
    metadata_a = PathMetadata("package-a", "project", "package", str(tmp_path / "a"))
    metadata_b = PathMetadata("package-b", "project", "package", str(tmp_path / "b"))
    resolved = ResolvedPaths(
        prompts=[
            ResolvedResource(str(missing), True, metadata_a),
            ResolvedResource(str(good), True, metadata_b),
        ]
    )

    report = await materialize_resolved_async(resolved, root=tmp_path)

    packages = {package.name: package for package in report.packages}
    assert [prompt.name for prompt in packages["package-b"].prompts] == ["good"]
    assert not packages["package-a"].prompts


def test_explicit_stream_options_override_extra() -> None:
    model = {
        "id": "faux", "name": "faux", "api": "faux", "provider": "faux",
        "baseUrl": "", "reasoning": False, "input": ["text"],
        "cost": {"input": 0.0, "output": 0.0, "cacheRead": 0.0, "cacheWrite": 0.0},
        "contextWindow": 128000, "maxTokens": 4096,
    }
    cfg = AgentLoopConfig(
        model=model,  # type: ignore[arg-type]
        convertToLlm=lambda messages: messages,  # type: ignore[arg-type,return-value]
        apiKey="typed-key",
        timeoutMs=100,
        extra={"apiKey": "extra-key", "timeoutMs": 999, "custom": True},
    )

    options = cfg.to_stream_options()

    assert options["apiKey"] == "typed-key"
    assert options["timeoutMs"] == 100
    assert options["custom"] is True
