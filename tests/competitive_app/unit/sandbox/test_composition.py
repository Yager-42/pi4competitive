"""Offline contract tests for Phase E composition (E3/E4/E5, feature O4/O8/O10/O13).

Covers the production executor/lifecycle wiring without Docker: lazy acquire,
never-release, sanitized error frames, once-only lifecycle calls, workspace
retention vs removal, startup handshake/canary, and the fail-closed
``build_application_state`` composition (no env/YAML/CLI bypass).
"""
from __future__ import annotations

import asyncio
import os
import json
from pathlib import Path
from typing import Any

import pytest

from competitive_app.adapter.out.sandbox.approved_registry import (
    ApprovedRegistryError,
    ApprovedToolRegistry,
    parse_approved_manifest,
)
from competitive_app.adapter.out.sandbox.lifecycle import CANARY_SESSION_ID, SandboxLifecycle
from competitive_app.adapter.out.sandbox.protocol import PROTOCOL_NAME, PROTOCOL_VERSION, RpcFrame
from competitive_app.adapter.out.sandbox.sandbox_tool_executor import (
    SandboxToolExecutionError,
    SandboxToolExecutor,
)
from competitive_app.adapter.out.sandbox.utils.sandbox_id import derive_sandbox_id
from earendil_works.pi_agent import AgentTool, AgentToolResult, ToolExecutionTarget


# --------------------------------------------------------------------------- fakes


async def _echo(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
) -> dict[str, Any]:
    return {"content": [], "details": params}


async def _host_execute_spy(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
) -> dict[str, Any]:
    raise AssertionError("host tool.execute must never run in the sandbox path")


def _tool(name: str = "echo", execute: Any = _echo) -> AgentTool:
    return AgentTool(
        name=name,
        description=name,
        parameters={"type": "object"},
        label=name,
        execute=execute,
        executionTarget=ToolExecutionTarget(__name__, execute.__name__),
    )


def _registry(*tools: AgentTool) -> ApprovedToolRegistry:
    return ApprovedToolRegistry.from_tools(list(tools), allowed_module_prefixes=(__name__,))


def _frame(frame_type: str, sequence: int, **extra: Any) -> RpcFrame:
    mapping: dict[str, Any] = {
        "protocolVersion": PROTOCOL_VERSION,
        "scopeId": "c" * 64,
        "toolCallId": "call_1",
        "sequence": sequence,
        "type": frame_type,
    }
    mapping.update(extra)
    return RpcFrame(
        protocol_version=mapping["protocolVersion"],
        scope_id=mapping["scopeId"],
        tool_call_id=mapping["toolCallId"],
        sequence=mapping["sequence"],
        type=mapping["type"],  # type: ignore[arg-type]
        result=mapping.get("result"),
        error=mapping.get("error"),
    )


class _FakeSandbox:
    def __init__(self, scope_id: str) -> None:
        self.id = scope_id
        self.requests: list[Any] = []
        self.frames: list[RpcFrame] = []
        self.terminal: RpcFrame | None = None
        self.closed = False

    async def execute_worker(self, request: Any, on_frame: Any, *, signal: Any = None) -> RpcFrame:
        self.requests.append(request)
        for frame in self.frames:
            result = on_frame(frame)
            if asyncio.iscoroutine(result):
                await result
        assert self.terminal is not None
        return self.terminal

    async def close(self) -> None:
        self.closed = True


class _FakeProvider:
    def __init__(self) -> None:
        self.acquires: list[str] = []
        self.releases: list[str] = []
        self.destroys: list[str] = []
        self.sandboxes: dict[str, _FakeSandbox] = {}
        self.shutdown_called = False

    async def acquire(self, scope_id: str) -> _FakeSandbox:
        self.acquires.append(scope_id)
        return self.sandboxes.setdefault(scope_id, _FakeSandbox(scope_id))

    async def release(self, scope_id: str) -> None:
        self.releases.append(scope_id)

    async def destroy_scope(self, scope_id: str) -> None:
        self.destroys.append(scope_id)
        self.sandboxes.pop(scope_id, None)

    async def get_info(self, scope_id: str) -> None:
        return None

    async def shutdown(self) -> None:
        self.shutdown_called = True


# ------------------------------------------------------------------- executor


@pytest.mark.asyncio
async def test_executor_acquires_lazily_and_never_releases() -> None:
    provider = _FakeProvider()
    executor = SandboxToolExecutor(registry=_registry(_tool()), provider=provider)
    assert provider.acquires == []  # no execute → no container
    provider.sandboxes["a" * 64] = _FakeSandbox("a" * 64)
    provider.sandboxes["a" * 64].terminal = _frame("result", 1, result={"content": [], "details": {}})

    await executor.execute(
        scope_id="a" * 64,
        tool=_tool(),
        tool_call_id="call_1",
        params={"text": "x"},
        signal=None,
        on_update=lambda _result: None,
    )
    assert provider.acquires == ["a" * 64]
    assert provider.releases == []  # E3: outer run owns the release


@pytest.mark.asyncio
async def test_executor_uses_registry_target_not_model_supplied() -> None:
    provider = _FakeProvider()
    executor = SandboxToolExecutor(registry=_registry(_tool()), provider=provider)
    tool = _tool()
    sandbox = provider.sandboxes.setdefault("a" * 64, _FakeSandbox("a" * 64))
    sandbox.terminal = _frame("result", 1, result={"content": [], "details": {}})
    await executor.execute(
        scope_id="a" * 64,
        tool=tool,
        tool_call_id="call_9",
        params={"text": "x"},
        signal=None,
        on_update=lambda _result: None,
    )
    request = provider.sandboxes["a" * 64].requests[0]
    assert request.tool_call_id == "call_9"
    assert request.target == {"module": __name__, "qualname": "_echo"}
    assert request.tool_name == "echo"


@pytest.mark.asyncio
async def test_executor_delivers_update_frames_in_order() -> None:
    provider = _FakeProvider()
    executor = SandboxToolExecutor(registry=_registry(_tool()), provider=provider)
    sandbox = provider.sandboxes.setdefault("a" * 64, _FakeSandbox("a" * 64))
    sandbox.frames = [
        _frame("update", 1, result={"content": [{"type": "text", "text": "first"}], "details": {"n": 1}}),
        _frame("update", 2, result={"content": [{"type": "text", "text": "second"}]}),
    ]
    sandbox.terminal = _frame("result", 3, result={"content": [{"type": "text", "text": "final"}]})
    seen: list[AgentToolResult] = []
    terminal = await executor.execute(
        scope_id="a" * 64,
        tool=_tool(),
        tool_call_id="call_1",
        params={},
        signal=None,
        on_update=seen.append,
    )
    assert [r["content"][0]["text"] for r in seen] == ["first", "second"]
    assert terminal["content"][0]["text"] == "final"


@pytest.mark.asyncio
async def test_executor_error_frame_raises_sanitized_error_without_host_call() -> None:
    provider = _FakeProvider()
    registry = _registry(_tool("echo", _host_execute_spy))
    executor = SandboxToolExecutor(registry=registry, provider=provider)
    sandbox = provider.sandboxes.setdefault("a" * 64, _FakeSandbox("a" * 64))
    sandbox.terminal = _frame(
        "error",
        1,
        error={"safeMessage": "worker blew up", "code": "sandbox_oom", "retryable": True},
    )
    with pytest.raises(SandboxToolExecutionError) as caught:
        await executor.execute(
            scope_id="a" * 64,
            tool=_tool("echo", _host_execute_spy),
            tool_call_id="call_1",
            params={},
            signal=None,
            on_update=lambda _result: None,
        )
    assert caught.value.message == "worker blew up"
    assert caught.value.details["code"] == "sandbox_oom"
    assert caught.value.details["retryable"] is True
    assert provider.releases == []  # no independent release on error either


@pytest.mark.asyncio
async def test_executor_maps_result_fields() -> None:
    provider = _FakeProvider()
    executor = SandboxToolExecutor(registry=_registry(_tool()), provider=provider)
    sandbox = provider.sandboxes.setdefault("a" * 64, _FakeSandbox("a" * 64))
    sandbox.terminal = _frame(
        "result",
        1,
        result={
            "content": [{"type": "text", "text": "ok"}],
            "details": {"used": 2},
            "usage": {"input_tokens": 10},
            "addedToolNames": ["extra"],
            "terminate": True,
        },
    )
    terminal = await executor.execute(
        scope_id="a" * 64,
        tool=_tool(),
        tool_call_id="call_1",
        params={},
        signal=None,
        on_update=lambda _result: None,
    )
    assert terminal["details"] == {"used": 2}
    assert terminal["usage"] == {"input_tokens": 10}
    assert terminal["addedToolNames"] == ["extra"]
    assert terminal["terminate"] is True


@pytest.mark.asyncio
async def test_executor_rejects_unapproved_tool_without_acquire() -> None:
    provider = _FakeProvider()
    executor = SandboxToolExecutor(registry=_registry(_tool("echo")), provider=provider)
    with pytest.raises(ApprovedRegistryError, match="not approved"):
        await executor.execute(
            scope_id="a" * 64,
            tool=_tool("other"),
            tool_call_id="call_1",
            params={},
            signal=None,
            on_update=lambda _result: None,
        )
    assert provider.acquires == []


# ------------------------------------------------------------------ lifecycle


def _lifecycle(tmp_path: Path, provider: _FakeProvider | None = None) -> tuple[SandboxLifecycle, _FakeProvider]:
    provider = provider or _FakeProvider()
    return (
        SandboxLifecycle(
            provider=provider,
            registry=_registry(_tool()),
            executor=SandboxToolExecutor(registry=_registry(_tool()), provider=provider),  # type: ignore[arg-type]
            sandbox_root=tmp_path,
            backend=None,
        ),
        provider,
    )


def test_lifecycle_scope_is_stable_and_parent_bound() -> None:
    assert derive_sandbox_id("session-1") == derive_sandbox_id("session-1")
    assert derive_sandbox_id("session-1") != derive_sandbox_id("session-2")
    with pytest.raises(ValueError, match="non-empty"):
        derive_sandbox_id("")


@pytest.mark.asyncio
async def test_lifecycle_release_forwards_once_and_destroy_preserves_workspace(tmp_path: Path) -> None:
    lifecycle, provider = _lifecycle(tmp_path)
    scope = lifecycle.scope_for("session-1")
    workspace = tmp_path / scope
    workspace.mkdir(parents=True)
    (workspace / "note.txt").write_text("keep me", encoding="utf-8")

    await lifecycle.release(session_id="session-1")
    assert provider.releases == [scope]
    await lifecycle.release(session_id="session-1")  # idempotent forward; provider owns dedupe
    assert provider.releases == [scope, scope]

    await lifecycle.destroy(session_id="session-1")
    assert provider.destroys == [scope]
    assert workspace.is_dir()  # E4: abort preserves the workspace
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "keep me"


@pytest.mark.asyncio
async def test_lifecycle_delete_workspace_removes_only_derived_dir(tmp_path: Path) -> None:
    lifecycle, provider = _lifecycle(tmp_path)
    scope = lifecycle.scope_for("session-1")
    workspace = tmp_path / scope
    workspace.mkdir(parents=True)
    (tmp_path / f"{scope}.lock").touch()
    other = tmp_path / ("f" * 64)
    other.mkdir()

    await lifecycle.delete_workspace(session_id="session-1")
    assert provider.destroys == [scope]
    assert not workspace.exists()
    assert not (tmp_path / f"{scope}.lock").exists()
    assert other.is_dir()  # untouched sibling scope


@pytest.mark.asyncio
async def test_lifecycle_shutdown_forwards(tmp_path: Path) -> None:
    lifecycle, provider = _lifecycle(tmp_path)
    await lifecycle.shutdown()
    assert provider.shutdown_called

@pytest.mark.asyncio
async def test_lifecycle_verify_startup_manifest_handshake_and_canary(tmp_path: Path) -> None:
    provider = _FakeProvider()
    registry = _registry(_tool())
    lifecycle = SandboxLifecycle(
        provider=provider,
        registry=registry,
        executor=SandboxToolExecutor(registry=registry, provider=provider),
        sandbox_root=tmp_path,
        backend=_ManifestBackend(registry),
    )
    sandbox = provider.sandboxes.setdefault(derive_sandbox_id(CANARY_SESSION_ID), _FakeSandbox("c" * 64))
    sandbox.terminal = _frame(
        "result", 1, result={"content": [{"type": "text", "text": "canary"}]}
    )
    await lifecycle.verify_startup(build_identity="sha256:abc")
    # canary scope acquired then destroyed; no container left behind
    assert provider.destroys == [derive_sandbox_id(CANARY_SESSION_ID)]
    assert provider.sandboxes == {}


@pytest.mark.asyncio
async def test_lifecycle_verify_startup_bad_manifest_fails_closed(tmp_path: Path) -> None:
    provider = _FakeProvider()
    registry = _registry(_tool())
    lifecycle = SandboxLifecycle(
        provider=provider,
        registry=registry,
        executor=SandboxToolExecutor(registry=registry, provider=provider),
        sandbox_root=tmp_path,
        backend=_ManifestBackend(registry, retarget={"echo": {"module": __name__, "qualname": "_other"}}),
    )
    with pytest.raises(ApprovedRegistryError, match="worker manifest target mismatch"):
        await lifecycle.verify_startup(build_identity="sha256:abc")
    assert provider.acquires == []  # fail before any canary container


@pytest.mark.asyncio
async def test_lifecycle_verify_startup_canary_mismatch_still_destroys(tmp_path: Path) -> None:
    provider = _FakeProvider()
    registry = _registry(_tool())
    lifecycle = SandboxLifecycle(
        provider=provider,
        registry=registry,
        executor=SandboxToolExecutor(registry=registry, provider=provider),
        sandbox_root=tmp_path,
        backend=_ManifestBackend(registry),
    )
    sandbox = provider.sandboxes.setdefault(derive_sandbox_id(CANARY_SESSION_ID), _FakeSandbox("c" * 64))
    sandbox.terminal = _frame("result", 1, result={"content": [{"type": "text", "text": "WRONG"}]})
    with pytest.raises(RuntimeError, match="unexpected content"):
        await lifecycle.verify_startup(build_identity="sha256:abc")
    assert provider.destroys == [derive_sandbox_id(CANARY_SESSION_ID)]  # unwound


class _ManifestBackend:
    def __init__(
        self,
        registry: ApprovedToolRegistry,
        retarget: dict[str, dict[str, str]] | None = None,
    ) -> None:
        tools = {
            name: (retarget or {}).get(name, binding.to_mapping())
            for name, binding in registry.bindings.items()
        }
        self._payload = json.dumps(
            {
                "protocol": PROTOCOL_NAME,
                "protocolVersion": PROTOCOL_VERSION,
                "buildIdentity": "sha256:abc",
                "tools": tools,
            }
        ).encode("utf-8")

    def read_baked_manifest(self) -> bytes:
        return self._payload


# -------------------------------------------------- wiring fail-closed (O21)


def _minimal_config(tmp_path: Path) -> Any:
    from competitive_app.wiring import AppConfig, SandboxAppConfig

    return AppConfig(
        sessions_cwd="test",
        sessions_root=str(tmp_path / "sessions"),
        app_db=str(tmp_path / "app.db"),
        use_faux=True,
        sandbox=SandboxAppConfig(root=str(tmp_path / "sandboxes")),
        capability_packages_enabled=["echo_example"],
    )


class _FakeNativeProvider:
    """Native provider twin: records composition kwargs, serves the canary."""

    instances: list["_FakeNativeProvider"] = []

    def __init__(
        self,
        *,
        sandbox_root: Any,
        environment: dict[str, str],
        manifest_path: Any = None,
        **kwargs: Any,
    ) -> None:
        del kwargs
        self.sandbox_root = sandbox_root
        self.environment = environment
        self.manifest_path = manifest_path
        self.shutdown_called = False
        self.started = False
        _FakeNativeProvider.instances.append(self)

    async def start(self) -> None:
        self.started = True

    async def acquire(self, scope_id: str) -> Any:
        sandbox = _FakeSandbox(scope_id)
        sandbox.terminal = _frame("result", 1, result={"content": [{"type": "text", "text": "canary"}]})
        return sandbox

    async def release(self, scope_id: str) -> None:
        return None

    async def destroy_scope(self, scope_id: str) -> None:
        return None

    async def get_info(self, scope_id: str) -> None:
        return None

    async def shutdown(self) -> None:
        self.shutdown_called = True


@pytest.mark.asyncio
async def test_wiring_native_composition_writes_manifest_and_runs_canary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from competitive_app import wiring as wiring_mod
    from competitive_app.adapter.out.sandbox.approved_registry import load_approved_manifest
    from competitive_app.adapter.out.sandbox.utils.sandbox_id import derive_sandbox_id

    monkeypatch.setattr(wiring_mod, "NativeSandboxProvider", _FakeNativeProvider)
    _FakeNativeProvider.instances.clear()
    state = await wiring_mod.build_application_state(_minimal_config(tmp_path))
    assert state.sandbox is not None
    assert state.sandbox.scope_for("session-1") == derive_sandbox_id("session-1")

    provider = _FakeNativeProvider.instances[0]
    assert provider.started is True
    assert not provider.shutdown_called
    assert Path(provider.manifest_path).is_file()
    manifest = load_approved_manifest(provider.manifest_path)
    assert "echo" in manifest.bindings  # registry subset handshake source
    assert manifest.build_identity.startswith("competitive-app-")

    # The provider saw the allowlisted env surface, including the capability root
    # needed for loader-generated top-level imports.
    assert "TAVILY_API_KEY" in provider.environment
    pythonpath = (provider.environment.get("PYTHONPATH") or "").split(os.pathsep)
    capability_root = (Path.cwd() / "capability_packages").resolve()
    assert str(capability_root) in pythonpath
    assert provider.environment.get("DATABASE_URL") is None
    await state.shutdown()
    assert provider.shutdown_called is True


@pytest.mark.asyncio
async def test_wiring_manifest_write_failure_unwinds_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from competitive_app import wiring as wiring_mod

    monkeypatch.setattr(wiring_mod, "NativeSandboxProvider", _FakeNativeProvider)
    _FakeNativeProvider.instances.clear()
    config = _minimal_config(tmp_path)
    config.sandbox.manifest = str(tmp_path / "missing-dir" / "approved_tools.json")
    # writing under a non-existent parent succeeds via mkdir; force failure by
    # making the target a directory
    (tmp_path / "missing-dir").mkdir()
    (tmp_path / "missing-dir" / "approved_tools.json").mkdir()
    with pytest.raises((IsADirectoryError, PermissionError)):
        await wiring_mod.build_application_state(config)
    assert _FakeNativeProvider.instances == []  # provider never constructed


@pytest.mark.asyncio
async def test_wiring_startup_failure_unwinds_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from competitive_app import wiring as wiring_mod
    from competitive_app.adapter.out.sandbox.approved_registry import ApprovedRegistryError

    class _BrokenProvider(_FakeNativeProvider):
        async def start(self) -> None:
            raise RuntimeError("sandbox readiness failed")

    monkeypatch.setattr(wiring_mod, "NativeSandboxProvider", _BrokenProvider)
    _FakeNativeProvider.instances.clear()
    with pytest.raises(RuntimeError, match="readiness failed"):
        await wiring_mod.build_application_state(_minimal_config(tmp_path))
    assert len(_FakeNativeProvider.instances) == 1
    assert _FakeNativeProvider.instances[0].shutdown_called is True  # unwound, no degraded state


@pytest.mark.asyncio
async def test_wiring_canary_failure_still_destroys_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from competitive_app import wiring as wiring_mod
    from competitive_app.adapter.out.sandbox.utils.sandbox_id import derive_sandbox_id

    class _FailingCanaryProvider(_FakeNativeProvider):
        async def acquire(self, scope_id: str) -> Any:
            sandbox = _FakeSandbox(scope_id)
            sandbox.terminal = _frame("error", 1, error={"code": "boom", "safeMessage": "boom"})
            return sandbox

    monkeypatch.setattr(wiring_mod, "NativeSandboxProvider", _FailingCanaryProvider)
    _FakeNativeProvider.instances.clear()
    with pytest.raises(Exception, match="canary"):
        await wiring_mod.build_application_state(_minimal_config(tmp_path))
    assert len(_FakeNativeProvider.instances) == 1
    assert _FakeNativeProvider.instances[0].shutdown_called is True


@pytest.mark.asyncio
async def test_wiring_doubles_must_be_paired(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from competitive_app import wiring as wiring_mod

    with pytest.raises(ValueError, match="must be provided together"):
        await wiring_mod.build_application_state(
            _minimal_config(tmp_path),
            tool_executor=object(),  # lifecycle missing
        )


@pytest.mark.asyncio
async def test_wiring_accepts_python_only_doubles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """E5: explicit Python-only doubles bypass the native composition."""
    from competitive_app import wiring as wiring_mod

    class _Exec:
        async def execute(self, **kwargs: Any) -> None:
            return None

    class _Life:
        async def release(self, **kwargs: Any) -> None:
            return None

        async def destroy(self, **kwargs: Any) -> None:
            return None

        async def delete_workspace(self, **kwargs: Any) -> None:
            return None

        async def shutdown(self) -> None:
            return None

    state = await wiring_mod.build_application_state(
        _minimal_config(tmp_path),
        tool_executor=_Exec(),
        sandbox_lifecycle=_Life(),
    )
    assert state.sandbox is not None
    await state.shutdown()
