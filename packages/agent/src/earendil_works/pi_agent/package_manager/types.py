"""Shared shapes for local package-manager subset.

upstream: packages/coding-agent/src/core/package-manager.ts (types + Resolved*)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from earendil_works.pi_agent.harness.prompt_templates import PromptTemplate
from earendil_works.pi_agent.harness.skills import Skill
from earendil_works.pi_agent.types import AgentTool

SourceScope = Literal["user", "project", "temporary"]
ResourceOrigin = Literal["package", "top-level"]
ResourceType = Literal["extensions", "skills", "prompts", "themes"]
MissingSourceAction = Literal["skip", "error"]  # "install" deliberately omitted (ADR 0006)

RESOURCE_TYPES: tuple[ResourceType, ...] = ("extensions", "skills", "prompts", "themes")
PACKAGE_ROOT_DEFAULT = "capability_packages"

# Host delta: Python extensions use .py (upstream: .ts|.js).
FILE_PATTERNS: dict[ResourceType, str] = {
    "extensions": r"\.py$",
    "skills": r"\.md$",
    "prompts": r"\.md$",
    "themes": r"\.json$",
}


@dataclass(frozen=True)
class PathMetadata:
    source: str
    scope: SourceScope
    origin: ResourceOrigin
    baseDir: str | None = None


@dataclass(frozen=True)
class ResolvedResource:
    path: str
    enabled: bool
    metadata: PathMetadata


@dataclass
class ResolvedPaths:
    extensions: list[ResolvedResource] = field(default_factory=list)
    skills: list[ResolvedResource] = field(default_factory=list)
    prompts: list[ResolvedResource] = field(default_factory=list)
    themes: list[ResolvedResource] = field(default_factory=list)


@dataclass(frozen=True)
class PiManifest:
    extensions: list[str] | None = None
    skills: list[str] | None = None
    prompts: list[str] | None = None
    themes: list[str] | None = None


@dataclass(frozen=True)
class PackageFilter:
    autoload: bool | None = None
    extensions: list[str] | None = None
    skills: list[str] | None = None
    prompts: list[str] | None = None
    themes: list[str] | None = None


@dataclass
class ResourceDiagnostic:
    level: Literal["info", "warn", "error"]
    package: str | None
    path: str | None
    message: str


@dataclass
class LoadedPackage:
    name: str
    root: str
    tools: list[AgentTool] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    prompts: list[PromptTemplate] = field(default_factory=list)


@dataclass
class LoadReport:
    root: Path
    resolved: ResolvedPaths
    packages: list[LoadedPackage] = field(default_factory=list)
    tools: list[AgentTool] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    prompts: list[PromptTemplate] = field(default_factory=list)
    diagnostics: list[ResourceDiagnostic] = field(default_factory=list)
    extension_result: Any | None = None
    extension_runner: Any | None = None

    def tool_names(self) -> list[str]:
        return [t.name for t in self.tools]


# Internal accumulator (mirrors ResourceAccumulator)
ResourceEntry = dict[str, Any]  # {"metadata": PathMetadata, "enabled": bool}
ResourceMap = dict[str, ResourceEntry]


@dataclass
class ResourceAccumulator:
    extensions: ResourceMap = field(default_factory=dict)
    skills: ResourceMap = field(default_factory=dict)
    prompts: ResourceMap = field(default_factory=dict)
    themes: ResourceMap = field(default_factory=dict)


__all__ = [
    "FILE_PATTERNS",
    "LoadReport",
    "LoadedPackage",
    "MissingSourceAction",
    "PACKAGE_ROOT_DEFAULT",
    "PathMetadata",
    "PiManifest",
    "PackageFilter",
    "RESOURCE_TYPES",
    "ResolvedPaths",
    "ResolvedResource",
    "ResourceAccumulator",
    "ResourceDiagnostic",
    "ResourceEntry",
    "ResourceMap",
    "ResourceOrigin",
    "ResourceType",
    "SourceScope",
]

