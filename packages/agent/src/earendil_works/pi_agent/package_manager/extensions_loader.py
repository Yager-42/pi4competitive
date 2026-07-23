"""Load Python capability extensions → AgentTool registration.

upstream: packages/coding-agent/src/core/extensions/loader.ts
host-delta: .ts/jiti → importlib + register(api) / TOOLS factory
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from earendil_works.pi_agent.harness.prompt_templates import PromptTemplate
from earendil_works.pi_agent.harness.skills import Skill
from earendil_works.pi_agent.types import AgentTool

from .errors import PackageLoadError
from .types import ResourceDiagnostic


@dataclass
class CapabilityRegisterApi:
    """Minimal register API for capability packages (host delta of ExtensionAPI)."""

    tools: list[AgentTool] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    prompts: list[PromptTemplate] = field(default_factory=list)
    package_name: str | None = None

    def add_tool(self, tool: AgentTool) -> None:
        if not isinstance(tool, AgentTool):
            raise TypeError(f"add_tool expects AgentTool, got {type(tool)!r}")
        self.tools.append(tool)

    def add_skill(self, skill: Skill) -> None:
        if not isinstance(skill, Skill):
            raise TypeError(f"add_skill expects Skill, got {type(skill)!r}")
        self.skills.append(skill)

    def add_prompt_template(self, template: PromptTemplate) -> None:
        if not isinstance(template, PromptTemplate):
            raise TypeError(f"add_prompt_template expects PromptTemplate, got {type(template)!r}")
        self.prompts.append(template)

    # camelCase aliases for upstream-ish extension authors
    def addTool(self, tool: AgentTool) -> None:  # noqa: N802
        self.add_tool(tool)

    def addSkill(self, skill: Skill) -> None:  # noqa: N802
        self.add_skill(skill)

    def addPromptTemplate(self, template: PromptTemplate) -> None:  # noqa: N802
        self.add_prompt_template(template)


@dataclass
class ExtensionLoadResult:
    path: str
    tools: list[AgentTool] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    prompts: list[PromptTemplate] = field(default_factory=list)
    diagnostics: list[ResourceDiagnostic] = field(default_factory=list)


def _module_name_for(path: Path, package_name: str | None) -> str:
    stem = path.stem
    pkg = package_name or "capability"
    # Unique synthetic name — never import as capability_packages.* (contract forbid)
    safe = "".join(ch if ch.isalnum() else "_" for ch in f"pi_cap_{pkg}_{stem}_{abs(hash(str(path))) % 10_000_000}")
    return safe


def load_extension_module(
    path: str | Path,
    *,
    package_name: str | None = None,
    api: CapabilityRegisterApi | None = None,
) -> ExtensionLoadResult:
    """Import a .py extension and collect tools via register(api) or TOOLS/create_tools."""
    p = Path(path).resolve()
    result = ExtensionLoadResult(path=str(p))
    if not p.is_file() or p.suffix != ".py":
        result.diagnostics.append(
            ResourceDiagnostic(
                level="error",
                package=package_name,
                path=str(p),
                message=f"extension is not a Python file: {p}",
            )
        )
        return result

    register_api = api or CapabilityRegisterApi(package_name=package_name)
    module_name = _module_name_for(p, package_name)

    try:
        module = _import_file(p, module_name)
    except Exception as exc:  # noqa: BLE001 — surface as diagnostic
        result.diagnostics.append(
            ResourceDiagnostic(
                level="error",
                package=package_name,
                path=str(p),
                message=f"failed to import extension: {exc}",
            )
        )
        return result

    try:
        _invoke_registration(module, register_api)
    except Exception as exc:  # noqa: BLE001
        result.diagnostics.append(
            ResourceDiagnostic(
                level="error",
                package=package_name,
                path=str(p),
                message=f"extension register failed: {exc}",
            )
        )
        return result

    result.tools = list(register_api.tools)
    result.skills = list(register_api.skills)
    result.prompts = list(register_api.prompts)
    return result


def load_extensions(
    paths: list[str | Path],
    *,
    package_name: str | None = None,
    strict: bool = False,
) -> ExtensionLoadResult:
    """Load multiple extension modules; merge tools (first name wins per call)."""
    merged = ExtensionLoadResult(path=":".join(str(p) for p in paths))
    seen_tool_names: set[str] = set()

    for path in paths:
        part = load_extension_module(path, package_name=package_name)
        merged.diagnostics.extend(part.diagnostics)
        if part.diagnostics and any(d.level == "error" for d in part.diagnostics) and strict:
            raise PackageLoadError(part.diagnostics[-1].message)
        for tool in part.tools:
            if tool.name in seen_tool_names:
                merged.diagnostics.append(
                    ResourceDiagnostic(
                        level="warn",
                        package=package_name,
                        path=part.path,
                        message=f"duplicate tool name skipped: {tool.name}",
                    )
                )
                continue
            seen_tool_names.add(tool.name)
            merged.tools.append(tool)
        merged.skills.extend(part.skills)
        merged.prompts.extend(part.prompts)
    return merged


def _import_file(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise PackageLoadError(f"cannot create import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _invoke_registration(module: ModuleType, api: CapabilityRegisterApi) -> None:
    register: Callable[[CapabilityRegisterApi], Any] | None = getattr(module, "register", None)
    if callable(register):
        register(api)
        return

    create_tools = getattr(module, "create_tools", None)
    if callable(create_tools):
        tools = create_tools()
        for tool in tools or []:
            api.add_tool(tool)
        return

    tools_attr = getattr(module, "TOOLS", None)
    if tools_attr is not None:
        for tool in tools_attr:
            api.add_tool(tool)
        return

    # No registration surface — not an error (empty extension)


__all__ = [
    "CapabilityRegisterApi",
    "ExtensionLoadResult",
    "load_extension_module",
    "load_extensions",
]
