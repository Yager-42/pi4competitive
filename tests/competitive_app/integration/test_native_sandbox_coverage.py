"""O20 — native sandbox universal executor coverage.

G0 map §8.1: main/dynamic/extension/resume/ephemeral tool execution all
reach the sandboxed executor. The offline path replaces only the SRT
broker (fake broker fixture); the worker, registry, manifest staging, and
protocol round trip are the REAL production modules, so an assertion on
the echoed text proves the full registry -> manifest -> worker -> tool ->
frame path ran inside the sandbox plumbing. Ephemeral orchestration has no
product here (pi-sandbox ``subagent.ts`` is OMIT per G0 §2.2); the ephemeral
mode asserts a fresh agent session inherits the same executor with its own
derived scope.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

from earendil_works.pi_ai import create_models
from earendil_works.pi_ai.providers.faux import (
    faux_assistant_message,
    faux_provider,
    faux_tool_call,
)

from earendil_works.pi_agent import Agent, AgentHarness, AgentOptions, AgentTool
from earendil_works.pi_agent.harness.env.python_env import LocalFileSystem
from earendil_works.pi_agent.harness.session.jsonl_repo import JsonlSessionRepo
from earendil_works.pi_agent.package_manager import load_capability_packages

from competitive_app.adapter.out.sandbox.approved_registry import ApprovedToolRegistry
from competitive_app.adapter.out.sandbox.native.native_runtime import NativeRuntime
from competitive_app.adapter.out.sandbox.native.native_sandbox_provider import (
    NATIVE_WORKER_ENVIRONMENT,
    NativeSandboxProvider,
)
from competitive_app.adapter.out.sandbox.sandbox_tool_executor import SandboxToolExecutor
from competitive_app.adapter.out.sandbox.utils.sandbox_id import derive_sandbox_id
from competitive_app.wiring import _write_native_manifest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # capability_packages namespace import

FIXTURES = ROOT / "tests" / "competitive_app" / "unit" / "sandbox" / "native" / "fixtures"
FAKE_BROKER = {"module_path": str(FIXTURES / "fake_broker.py"), "exec_argv": []}


def _runtime_factory(workspace: Path, **kwargs: Any) -> NativeRuntime:
    kwargs["broker"] = FAKE_BROKER
    return NativeRuntime(workspace, **kwargs)


async def _sandbox_executor(tmp_path: Path) -> tuple[SandboxToolExecutor, AgentTool]:
    capability = await load_capability_packages(enabled=["echo_example"])
    registry = ApprovedToolRegistry.from_tools(list(capability.tools))
    manifest_path = tmp_path / "approved_tools.json"
    _write_native_manifest(registry, manifest_path)
    environment = {name: os.environ.get(name) for name in NATIVE_WORKER_ENVIRONMENT}
    pythonpath = [entry for entry in (environment.get("PYTHONPATH") or "").split(os.pathsep) if entry]
    for entry in (str(ROOT), str(ROOT / "capability_packages")):
        if entry not in pythonpath:
            pythonpath.append(entry)
    environment["PYTHONPATH"] = os.pathsep.join(pythonpath)
    provider = NativeSandboxProvider(
        sandbox_root=tmp_path / "sandboxes",
        environment=environment,
        manifest_path=manifest_path,
        runtime_factory=_runtime_factory,
    )
    executor = SandboxToolExecutor(registry=registry, provider=provider)
    return executor, next(iter(capability.tools))


class _EchoProbe:
    """Collect echoed tool-result text from agent turn_end events."""

    def __init__(self, agent: Any) -> None:
        self.texts: list[str] = []
        self._unsub = agent.subscribe(self._on_event)

    def _on_event(self, event: Any, _signal: Any) -> None:
        if event.get("type") != "turn_end":
            return None
        for result in event.get("toolResults") or []:
            for item in result.get("content") or []:
                if isinstance(item, dict) and item.get("type") == "text":
                    self.texts.append(str(item.get("text") or ""))
        return None

    def echoed(self) -> str:
        self._unsub()
        return "".join(self.texts)


class _FauxHarness:
    """Faux-model harness bound to the native sandbox executor."""

    def __init__(self, tmp_path: Path, executor: SandboxToolExecutor, tool: AgentTool, scope_id: str) -> None:
        self._tmp_path = tmp_path
        self._executor = executor
        self._tool = tool
        self._scope_id = scope_id
        self._faux = faux_provider()
        models = create_models()
        models.setProvider(self._faux["provider"])
        self._models = models

    def _set_responses(self, texts: list[str]) -> None:
        responses: list[Any] = []
        for text in texts:
            responses.append(faux_assistant_message([faux_tool_call("echo", {"text": text})]))
            responses.append(faux_assistant_message("done"))
        self._faux["setResponses"](responses)

    def agent(self) -> Agent:
        model = self._faux["getModel"]()
        assert model is not None
        return Agent(
            AgentOptions(
                stream_fn=self._models.streamSimple,
                initial_state={"model": model, "tools": [self._tool], "systemPrompt": "test"},
                tool_execution="sequential",
                tool_executor=self._executor,
                tool_execution_scope_id=self._scope_id,
            )
        )

    async def harness(self, session: Any = None) -> AgentHarness:
        model = self._faux["getModel"]()
        assert model is not None
        repo = JsonlSessionRepo(
            {"fs": LocalFileSystem(cwd=str(self._tmp_path)), "sessionsRoot": str(self._tmp_path / "sessions")}
        )
        if session is None:
            session = await repo.create({"cwd": str(self._tmp_path)})
        return AgentHarness(
            session=session,
            stream_fn=self._models.streamSimple,
            model=model,
            tools=[self._tool],
            tool_execution="sequential",
            tool_executor=self._executor,
            tool_execution_scope_id=self._scope_id,
        )


@pytest.mark.asyncio
async def test_main_tool_call_runs_through_native_sandbox(tmp_path: Path) -> None:
    executor, tool = await _sandbox_executor(tmp_path)
    harness = _FauxHarness(tmp_path, executor, tool, derive_sandbox_id("main-scope"))
    harness._set_responses(["main"])
    agent = harness.agent()
    probe = _EchoProbe(agent)
    await agent.prompt("run")
    assert probe.echoed() == "main"


@pytest.mark.asyncio
async def test_extension_provided_tool_runs_through_native_sandbox(tmp_path: Path) -> None:
    executor, tool = await _sandbox_executor(tmp_path)
    assert tool.executionTarget is not None
    assert (
        tool.executionTarget.module.startswith("capability_packages.")
        or tool.executionTarget.module.startswith("echo_example.")
    )
    harness = _FauxHarness(tmp_path, executor, tool, derive_sandbox_id("extension-scope"))
    harness._set_responses(["extension"])
    agent = harness.agent()
    probe = _EchoProbe(agent)
    await agent.prompt("run")
    assert probe.echoed() == "extension"


@pytest.mark.asyncio
async def test_dynamic_tool_replacement_keeps_sandbox_execution(tmp_path: Path) -> None:
    executor, tool = await _sandbox_executor(tmp_path)
    harness = _FauxHarness(tmp_path, executor, tool, derive_sandbox_id("dynamic-scope"))
    harness._set_responses(["first", "second"])
    agent = harness.agent()
    probe = _EchoProbe(agent)
    await agent.prompt("first")
    # Simulate dynamic re-registration: a fresh tool object with the same
    # approved target replaces the registered one between turns.
    replacement = AgentTool(
        name=tool.name,
        description=tool.description,
        parameters=tool.parameters,
        label=tool.label,
        execute=tool.execute,
        executionMode=tool.executionMode,
        executionTarget=tool.executionTarget,
    )
    agent.state.tools = [replacement]
    await agent.prompt("second")
    assert probe.echoed() == "firstsecond"


@pytest.mark.asyncio
async def test_resume_reuses_sandbox_scope(tmp_path: Path) -> None:
    executor, tool = await _sandbox_executor(tmp_path)
    harness = _FauxHarness(tmp_path, executor, tool, derive_sandbox_id("resume-scope"))
    harness._set_responses(["first", "second"])
    repo = JsonlSessionRepo(
        {"fs": LocalFileSystem(cwd=str(tmp_path)), "sessionsRoot": str(tmp_path / "sessions")}
    )
    session = await repo.create({"cwd": str(tmp_path)})
    first = await harness.harness(session)
    probe_first = _EchoProbe(first.agent)
    await first.prompt("first")
    assert probe_first.echoed() == "first"
    metadata = await session.get_metadata()
    first.close()
    resumed_session = await repo.open(metadata)
    resumed = await harness.harness(resumed_session)
    probe_second = _EchoProbe(resumed.agent)
    await resumed.prompt("second")
    resumed.close()
    assert probe_second.echoed() == "second"


@pytest.mark.asyncio
async def test_ephemeral_agent_inherits_executor_with_own_scope(tmp_path: Path) -> None:
    executor, tool = await _sandbox_executor(tmp_path)
    parent = _FauxHarness(tmp_path, executor, tool, derive_sandbox_id("parent-scope"))
    parent._set_responses(["parent"])
    parent_agent = parent.agent()
    probe_parent = _EchoProbe(parent_agent)
    await parent_agent.prompt("parent")
    assert probe_parent.echoed() == "parent"
    # Ephemeral: a fresh session/agent on the same executor derives its own scope.
    child = _FauxHarness(tmp_path, executor, tool, derive_sandbox_id("child-scope"))
    child._set_responses(["child"])
    child_agent = child.agent()
    probe_child = _EchoProbe(child_agent)
    await child_agent.prompt("child")
    assert probe_child.echoed() == "child"
