"""Immutable host-side approved AgentTool target registry.

NEW-HOST: Pi's provider-neutral seam carries target metadata, while this App
adapter owns production binding and image-manifest policy.  The model never
supplies or selects a target.
"""
from __future__ import annotations

import importlib
import inspect
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from earendil_works.pi_agent.tool_execution import ToolExecutionTarget, derive_tool_execution_target
from earendil_works.pi_agent.types import AgentTool

from .protocol import PROTOCOL_NAME, PROTOCOL_VERSION, RpcProtocolError


def _imported_target_callable(target: ToolExecutionTarget) -> Any | None:
    """Import a host-approved target module and resolve its callable."""
    if (
        not target.module
        or "." in target.qualname
        or "<locals>" in target.qualname
        or "<lambda>" in target.qualname
    ):
        return None
    try:
        module = importlib.import_module(target.module)
    except Exception:  # noqa: BLE001
        return None
    value = getattr(module, target.qualname, None)
    if not inspect.iscoroutinefunction(value):
        return None
    return value


def _lineage_matches(tool: AgentTool, target: ToolExecutionTarget) -> bool:
    """The recorded target matches the tool callable's explicit lineage.

    The local extension loader imports entry files under generated
    ``pi_extension_*`` module names; the wrap step remaps those to real
    package paths so the image can import them.  A remapped target is
    accepted only when the remapped module resolves to the same callable
    (byte-identical code object).
    """
    derived = derive_tool_execution_target(tool.execute)
    if derived is None or derived.qualname != target.qualname:
        return False
    if derived.module == target.module:
        return True
    if not derived.module.startswith("pi_extension_"):
        return False
    original = inspect.unwrap(tool.execute)
    imported = _imported_target_callable(target)
    return imported is not None and imported.__code__ == original.__code__


class ApprovedRegistryError(ValueError):
    """Raised when a host or baked target binding is not approved."""


@dataclass(frozen=True, slots=True)
class ApprovedToolBinding:
    name: str
    target: ToolExecutionTarget

    def to_mapping(self) -> dict[str, str]:
        return {"module": self.target.module, "qualname": self.target.qualname}


@dataclass(frozen=True, slots=True)
class ApprovedToolManifest:
    protocol: str
    protocol_version: int
    build_identity: str
    bindings: Mapping[str, ApprovedToolBinding]

    def __post_init__(self) -> None:
        object.__setattr__(self, "bindings", MappingProxyType(dict(self.bindings)))


@dataclass(frozen=True, slots=True)
class ApprovedToolRegistry:
    bindings: Mapping[str, ApprovedToolBinding]

    def __post_init__(self) -> None:
        object.__setattr__(self, "bindings", MappingProxyType(dict(self.bindings)))

    @classmethod
    def from_tools(
        cls,
        tools: Iterable[AgentTool],
        *,
        allowed_module_prefixes: tuple[str, ...] = (
            "capability_packages.",
            "earendil_works.pi_agent.",
        ),
    ) -> "ApprovedToolRegistry":
        bindings: dict[str, ApprovedToolBinding] = {}
        target_names: dict[ToolExecutionTarget, str] = {}
        for tool in tools:
            if tool.name in bindings:
                raise ApprovedRegistryError(f"duplicate approved tool name: {tool.name}")
            target = tool.executionTarget
            if target is None:
                raise ApprovedRegistryError(f"tool {tool.name} has no execution target")
            if not _lineage_matches(tool, target):
                raise ApprovedRegistryError(f"tool {tool.name} target does not match callable lineage")
            if not target.module.startswith(allowed_module_prefixes):
                raise ApprovedRegistryError(f"tool {tool.name} module is not approved: {target.module}")
            previous = target_names.get(target)
            if previous is not None:
                raise ApprovedRegistryError(f"target collision: {previous} and {tool.name}")
            binding = ApprovedToolBinding(tool.name, target)
            bindings[tool.name] = binding
            target_names[target] = tool.name
        if not bindings:
            raise ApprovedRegistryError("approved tool registry cannot be empty")
        return cls(bindings)

    @classmethod
    def from_manifest(cls, manifest: ApprovedToolManifest) -> "ApprovedToolRegistry":
        return cls(manifest.bindings)

    def binding_for(self, tool: AgentTool) -> ApprovedToolBinding:
        try:
            binding = self.bindings[tool.name]
        except KeyError as exc:
            raise ApprovedRegistryError(f"tool is not approved: {tool.name}") from exc
        if tool.executionTarget != binding.target:
            raise ApprovedRegistryError(f"tool target is rebound: {tool.name}")
        if not _lineage_matches(tool, binding.target):
            raise ApprovedRegistryError(f"tool callable lineage is rebound: {tool.name}")
        return binding

    def target_for(self, tool_name: str) -> ToolExecutionTarget:
        try:
            return self.bindings[tool_name].target
        except KeyError as exc:
            raise ApprovedRegistryError(f"tool is not approved: {tool_name}") from exc

    def validate_baked_manifest(self, manifest: ApprovedToolManifest) -> None:
        if manifest.protocol != PROTOCOL_NAME or manifest.protocol_version != PROTOCOL_VERSION:
            raise ApprovedRegistryError("worker manifest protocol mismatch")
        for name, binding in self.bindings.items():
            baked = manifest.bindings.get(name)
            if baked is None:
                raise ApprovedRegistryError(f"worker manifest is missing host tool: {name}")
            if baked.target != binding.target:
                raise ApprovedRegistryError(f"worker manifest target mismatch: {name}")


def _strict_json_manifest(raw: bytes) -> Any:
    def reject_constant(value: str) -> None:
        raise ApprovedRegistryError(f"non-finite manifest value: {value}")

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ApprovedRegistryError(f"duplicate manifest key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApprovedRegistryError("invalid approved tool manifest JSON") from exc


def parse_approved_manifest(value: Mapping[str, Any]) -> ApprovedToolManifest:
    expected = {"protocol", "protocolVersion", "buildIdentity", "tools"}
    actual = set(value)
    if actual != expected:
        raise ApprovedRegistryError(
            f"approved manifest fields mismatch: missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}"
        )
    if value["protocol"] != PROTOCOL_NAME or value["protocolVersion"] != PROTOCOL_VERSION:
        raise ApprovedRegistryError("approved manifest protocol mismatch")
    build_identity = value["buildIdentity"]
    if not isinstance(build_identity, str) or not build_identity:
        raise ApprovedRegistryError("approved manifest buildIdentity must be non-empty")
    tools = value["tools"]
    if not isinstance(tools, dict) or not tools:
        raise ApprovedRegistryError("approved manifest tools must be a non-empty object")
    bindings: dict[str, ApprovedToolBinding] = {}
    target_names: dict[ToolExecutionTarget, str] = {}
    for name, raw_target in tools.items():
        if not isinstance(name, str) or not name:
            raise ApprovedRegistryError("approved manifest tool names must be non-empty strings")
        if not isinstance(raw_target, dict) or set(raw_target) != {"module", "qualname"}:
            raise ApprovedRegistryError(f"invalid baked target for {name}")
        module, qualname = raw_target["module"], raw_target["qualname"]
        if not isinstance(module, str) or not module or not isinstance(qualname, str) or not qualname:
            raise ApprovedRegistryError(f"invalid baked target identity for {name}")
        target = ToolExecutionTarget(module, qualname)
        previous = target_names.get(target)
        if previous is not None:
            raise ApprovedRegistryError(f"baked target collision: {previous} and {name}")
        bindings[name] = ApprovedToolBinding(name, target)
        target_names[target] = name
    return ApprovedToolManifest(PROTOCOL_NAME, PROTOCOL_VERSION, build_identity, bindings)


def load_approved_manifest(path: str | Path) -> ApprovedToolManifest:
    try:
        value = _strict_json_manifest(Path(path).read_bytes())
    except OSError as exc:
        raise ApprovedRegistryError(f"cannot read approved tool manifest: {path}") from exc
    if not isinstance(value, dict):
        raise ApprovedRegistryError("approved tool manifest must be an object")
    return parse_approved_manifest(value)


def manifest_to_mapping(manifest: ApprovedToolManifest) -> dict[str, Any]:
    return {
        "protocol": manifest.protocol,
        "protocolVersion": manifest.protocol_version,
        "buildIdentity": manifest.build_identity,
        "tools": {name: binding.to_mapping() for name, binding in manifest.bindings.items()},
    }


__all__ = [
    "ApprovedRegistryError",
    "ApprovedToolBinding",
    "ApprovedToolManifest",
    "ApprovedToolRegistry",
    "load_approved_manifest",
    "manifest_to_mapping",
    "parse_approved_manifest",
]
