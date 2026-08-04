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


def _trusted_capability_root(capability_root: Path | str | None = None) -> Path:
    """Resolve the repository capability root using the package-manager API."""
    if capability_root is None:
        from earendil_works.pi_agent.package_manager import default_capability_root

        return default_capability_root()
    return Path(capability_root).resolve()


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


def _is_local_capability_module(
    module_name: str,
    *,
    capability_root: Path | str | None = None,
) -> bool:
    """Require a capability module's origin to be inside the trusted root."""
    try:
        module = importlib.import_module(module_name)
        module_file = getattr(module, "__file__", None)
        if not module_file:
            return False
        resolved = Path(module_file).resolve()
        root = _trusted_capability_root(capability_root)
        if not resolved.is_relative_to(root):
            return False
    except Exception:  # noqa: BLE001
        return False
    return True
def _canonical_target(
    target: ToolExecutionTarget,
    *,
    capability_root: Path | str | None = None,
) -> ToolExecutionTarget:
    """Map loader aliases to the import path available in the worker image."""
    if target.module.startswith("capability_packages.") or target.module.startswith("earendil_works."):
        return target
    if not _is_local_capability_module(target.module, capability_root=capability_root):
        return target
    canonical = ToolExecutionTarget(f"capability_packages.{target.module}", target.qualname)
    if _imported_target_callable(canonical) is None:
        return target
    return canonical


def _lineage_matches(
    tool: AgentTool,
    target: ToolExecutionTarget,
    *,
    capability_root: Path | str | None = None,
) -> bool:
    """The recorded target matches the tool callable's explicit lineage.

    Generated loader aliases and their canonical capability package paths are
    accepted only when they resolve to the same coroutine code object.
    """
    derived = derive_tool_execution_target(tool.execute)
    if derived is None or derived.qualname != target.qualname:
        return False
    if derived.module == target.module:
        return True
    original = inspect.unwrap(tool.execute)
    if (
        _canonical_target(derived, capability_root=capability_root) == target
        or derived.module.startswith("pi_extension_")
    ):
        imported = _imported_target_callable(target)
        return imported is not None and imported.__code__ == original.__code__
    return False


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
    capability_root: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "bindings", MappingProxyType(dict(self.bindings)))
        object.__setattr__(self, "capability_root", _trusted_capability_root(self.capability_root))

    @classmethod
    def from_tools(
        cls,
        tools: Iterable[AgentTool],
        *,
        allowed_module_prefixes: tuple[str, ...] | None = None,
        capability_root: Path | str | None = None,
    ) -> "ApprovedToolRegistry":
        trusted_root = _trusted_capability_root(capability_root)
        bindings: dict[str, ApprovedToolBinding] = {}
        target_names: dict[ToolExecutionTarget, str] = {}
        for tool in tools:
            if tool.name in bindings:
                raise ApprovedRegistryError(f"duplicate approved tool name: {tool.name}")
            target = tool.executionTarget
            if target is None:
                raise ApprovedRegistryError(f"tool {tool.name} has no execution target")
            if not _lineage_matches(tool, target, capability_root=trusted_root):
                raise ApprovedRegistryError(f"tool {tool.name} target does not match callable lineage")
            if allowed_module_prefixes is None:
                module_approved = (
                    target.module.startswith("earendil_works.pi_agent.")
                    or _is_local_capability_module(target.module, capability_root=trusted_root)
                )
            else:
                module_approved = target.module.startswith(allowed_module_prefixes)
                if module_approved and (
                    target.module == "capability_packages"
                    or target.module.startswith("capability_packages.")
                ):
                    module_approved = _is_local_capability_module(
                        target.module, capability_root=trusted_root
                    )
            if not module_approved:
                raise ApprovedRegistryError(f"tool {tool.name} module is not approved: {target.module}")
            previous = target_names.get(target)
            if previous is not None:
                raise ApprovedRegistryError(f"target collision: {previous} and {tool.name}")
            binding = ApprovedToolBinding(tool.name, target)
            bindings[tool.name] = binding
            target_names[target] = tool.name
        if not bindings:
            raise ApprovedRegistryError("approved tool registry cannot be empty")
        return cls(bindings, trusted_root)

    @classmethod
    def from_manifest(
        cls,
        manifest: ApprovedToolManifest,
        *,
        capability_root: Path | str | None = None,
    ) -> "ApprovedToolRegistry":
        """Load a host-produced manifest.

        The manifest is trusted for tools bound to non-capability modules
        (``earendil_works.*`` host bindings), but capability modules are still
        re-checked against the trusted root so a manifest edited outside the
        loader cannot smuggle an arbitrary import target.
        """
        trusted_root = _trusted_capability_root(capability_root)
        for tool_name, binding in manifest.bindings.items():
            target = binding.target
            if target.module == "capability_packages" or target.module.startswith("capability_packages."):
                if not _is_local_capability_module(target.module, capability_root=trusted_root):
                    raise ApprovedRegistryError(
                        f"tool {tool_name} module is not approved: {target.module}"
                    )
        return cls(manifest.bindings, trusted_root)

    def binding_for(self, tool: AgentTool) -> ApprovedToolBinding:
        try:
            binding = self.bindings[tool.name]
        except KeyError as exc:
            raise ApprovedRegistryError(f"tool is not approved: {tool.name}") from exc
        if tool.executionTarget is None or _canonical_target(
            tool.executionTarget, capability_root=self.capability_root
        ) != _canonical_target(binding.target, capability_root=self.capability_root):
            raise ApprovedRegistryError(f"tool target is rebound: {tool.name}")
        if not _lineage_matches(tool, binding.target, capability_root=self.capability_root):
            raise ApprovedRegistryError(f"tool callable lineage is rebound: {tool.name}")
        return binding

    def target_for(self, tool_name: str) -> ToolExecutionTarget:
        try:
            return self.bindings[tool_name].target
        except KeyError as exc:
            raise ApprovedRegistryError(f"tool is not approved: {tool_name}") from exc

    def validate_baked_manifest(
        self,
        manifest: ApprovedToolManifest,
        *,
        build_identity: str | None = None,
    ) -> None:
        if manifest.protocol != PROTOCOL_NAME or manifest.protocol_version != PROTOCOL_VERSION:
            raise ApprovedRegistryError("worker manifest protocol mismatch")
        if build_identity is not None and manifest.build_identity != build_identity:
            raise ApprovedRegistryError("worker manifest build identity mismatch")
        for name, binding in self.bindings.items():
            baked = manifest.bindings.get(name)
            if baked is None:
                raise ApprovedRegistryError(f"worker manifest is missing host tool: {name}")
            if baked.to_mapping() != binding.to_mapping():
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
