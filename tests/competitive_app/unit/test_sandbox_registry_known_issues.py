"""Focused regressions for capability approval trust-boundary issues."""
from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from competitive_app.adapter.out.sandbox import approved_registry as registry_module

from competitive_app.adapter.out.sandbox.approved_registry import (
    ApprovedRegistryError,
    ApprovedToolRegistry,
)
from earendil_works.pi_agent import AgentTool, ToolExecutionTarget


def _tool(name: str, execute: Any, module: str) -> AgentTool:
    return AgentTool(
        name=name,
        description=name,
        parameters={"type": "object"},
        label=name,
        execute=execute,
        executionTarget=ToolExecutionTarget(module, execute.__name__),
    )


def test_registry_accepts_capability_from_trusted_repository_root() -> None:
    module = importlib.import_module("capability_packages.echo_example.extensions.echo_tools")
    execute = module._echo_execute
    registry = ApprovedToolRegistry.from_tools(
        [_tool("echo", execute, "capability_packages.echo_example.extensions.echo_tools")]
    )
    assert registry.target_for("echo").module.startswith("capability_packages.")


def test_registry_rejects_shadowed_capability_module_outside_trusted_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module_name = "capability_packages.shadowed_capability"
    module = types.ModuleType(module_name)
    module.__file__ = str(tmp_path / "capability_packages" / "shadowed.py")
    exec(
        "async def execute(tool_call_id, params, signal=None, on_update=None):\n"
        "    return {'content': [], 'details': params}\n",
        module.__dict__,
    )
    monkeypatch.setitem(sys.modules, module_name, module)
    repo_root = Path(__file__).resolve().parents[3]
    with pytest.raises(ApprovedRegistryError, match="module is not approved"):
        ApprovedToolRegistry.from_tools(
            [_tool("shadowed", module.execute, module_name)],
            capability_root=repo_root / "capability_packages",
        )


def test_registry_rejects_unimportable_target_fail_closed() -> None:
    async def execute(tool_call_id: str, params: dict[str, Any], signal=None, on_update=None):
        return {"content": [], "details": params}

    with pytest.raises(ApprovedRegistryError):
        ApprovedToolRegistry.from_tools(
            [_tool("missing", execute, "capability_packages.not_importable")]
        )


def test_registry_converts_import_exception_to_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def execute(tool_call_id: str, params: dict[str, Any], signal=None, on_update=None):
        return {"content": [], "details": params}

    def explode(_name: str):
        raise KeyError("shadowed import")

    monkeypatch.setattr(registry_module.importlib, "import_module", explode)
    with pytest.raises(ApprovedRegistryError):
        ApprovedToolRegistry.from_tools(
            [_tool("broken", execute, "capability_packages.broken")]
        )


def test_from_manifest_rejects_capability_module_outside_trusted_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A manifest edited outside the loader must not smuggle an arbitrary
    capability import target: capability modules are re-checked against the
    trusted root even when the manifest itself came from the host."""
    module_name = "capability_packages.rogue_manifest"
    module = types.ModuleType(module_name)
    module.__file__ = str(tmp_path / "rogue.py")
    exec(
        "async def execute(tool_call_id, params, signal=None, on_update=None):\n"
        "    return {'content': [], 'details': params}\n",
        module.__dict__,
    )
    monkeypatch.setitem(sys.modules, module_name, module)
    manifest = registry_module.ApprovedToolManifest(
        protocol="agent-tool-rpc.v1",
        protocol_version=1,
        build_identity="rogue",
        bindings={
            "rogue": registry_module.ApprovedToolBinding(
                "rogue", ToolExecutionTarget(module_name, "execute")
            )
        },
    )
    repo_root = Path(__file__).resolve().parents[3]
    with pytest.raises(ApprovedRegistryError, match="module is not approved"):
        ApprovedToolRegistry.from_manifest(
            manifest, capability_root=repo_root / "capability_packages"
        )


def test_from_manifest_rejects_before_importing_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    imported: list[str] = []

    def forbidden_import(name: str):
        imported.append(name)
        raise AssertionError("untrusted target must not be imported")

    monkeypatch.setattr(registry_module.importlib, "import_module", forbidden_import)
    manifest = registry_module.ApprovedToolManifest(
        protocol="agent-tool-rpc.v1",
        protocol_version=1,
        build_identity="rogue",
        bindings={
            "rogue": registry_module.ApprovedToolBinding(
                "rogue", ToolExecutionTarget("capability_packages.not_trusted", "execute")
            )
        },
    )
    with pytest.raises(ApprovedRegistryError, match="module is not approved"):
        ApprovedToolRegistry.from_manifest(manifest, capability_root=tmp_path / "trusted")
    assert imported == []