"""Load resolved local resources into runtime objects.

upstream: packages/coding-agent/src/core/resource-loader.ts (local load intent)
themes / TUI omitted.
"""
from __future__ import annotations

from pathlib import Path

from earendil_works.pi_agent.harness.prompt_templates import PromptTemplate
from earendil_works.pi_agent.harness.skills import Skill, load_skill_from_file
from earendil_works.pi_agent.types import AgentTool

from .extensions_loader import ExtensionLoadResult, load_extension_module
from .types import (
    LoadReport,
    LoadedPackage,
    ResolvedPaths,
    ResolvedResource,
    ResourceDiagnostic,
)


def load_skill_resources(resources: list[ResolvedResource]) -> tuple[list[Skill], list[ResourceDiagnostic]]:
    skills: list[Skill] = []
    diags: list[ResourceDiagnostic] = []
    for res in resources:
        if not res.enabled:
            continue
        path = Path(res.path)
        try:
            if path.is_file():
                skills.append(load_skill_from_file(path))
            else:
                diags.append(
                    ResourceDiagnostic(
                        level="warn",
                        package=res.metadata.source,
                        path=res.path,
                        message=f"skill path missing: {res.path}",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            diags.append(
                ResourceDiagnostic(
                    level="error",
                    package=res.metadata.source,
                    path=res.path,
                    message=f"failed to load skill: {exc}",
                )
            )
    return skills, diags


def load_prompt_resources(resources: list[ResolvedResource]) -> tuple[list[PromptTemplate], list[ResourceDiagnostic]]:
    prompts: list[PromptTemplate] = []
    diags: list[ResourceDiagnostic] = []
    for res in resources:
        if not res.enabled:
            continue
        path = Path(res.path)
        try:
            if not path.is_file():
                diags.append(
                    ResourceDiagnostic(
                        level="warn",
                        package=res.metadata.source,
                        path=res.path,
                        message=f"prompt path missing: {res.path}",
                    )
                )
                continue
            text = path.read_text(encoding="utf-8")
            name = path.stem
            description: str | None = None
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    front = parts[1]
                    text = parts[2].lstrip("\n")
                    for line in front.splitlines():
                        if ":" in line:
                            k, v = line.split(":", 1)
                            k = k.strip().lower()
                            v = v.strip().strip("\"'")
                            if k == "name":
                                name = v
                            elif k == "description":
                                description = v
            prompts.append(PromptTemplate(name=name, content=text, description=description))
        except Exception as exc:  # noqa: BLE001
            diags.append(
                ResourceDiagnostic(
                    level="error",
                    package=res.metadata.source,
                    path=res.path,
                    message=f"failed to load prompt: {exc}",
                )
            )
    return prompts, diags


def load_extension_resources(
    resources: list[ResolvedResource],
    *,
    strict: bool = False,
) -> tuple[list[AgentTool], list[Skill], list[PromptTemplate], list[ResourceDiagnostic], dict[str, LoadedPackage]]:
    tools: list[AgentTool] = []
    skills: list[Skill] = []
    prompts: list[PromptTemplate] = []
    diags: list[ResourceDiagnostic] = []
    seen_tools: set[str] = set()
    by_pkg: dict[str, LoadedPackage] = {}

    for res in resources:
        if not res.enabled:
            continue
        pkg = by_pkg.setdefault(
            res.metadata.source,
            LoadedPackage(name=res.metadata.source, root=res.metadata.baseDir or res.metadata.source),
        )
        part: ExtensionLoadResult = load_extension_module(res.path, package_name=res.metadata.source)
        diags.extend(part.diagnostics)
        if strict and any(d.level == "error" for d in part.diagnostics):
            from .errors import PackageLoadError

            raise PackageLoadError(part.diagnostics[-1].message)
        for tool in part.tools:
            if tool.name in seen_tools:
                diags.append(
                    ResourceDiagnostic(
                        level="warn",
                        package=res.metadata.source,
                        path=res.path,
                        message=f"duplicate tool name skipped: {tool.name}",
                    )
                )
                continue
            seen_tools.add(tool.name)
            tools.append(tool)
            pkg.tools.append(tool)
        for skill in part.skills:
            skills.append(skill)
            pkg.skills.append(skill)
        for prompt in part.prompts:
            prompts.append(prompt)
            pkg.prompts.append(prompt)
    return tools, skills, prompts, diags, by_pkg


def materialize_resolved(
    resolved: ResolvedPaths,
    *,
    root: Path,
    strict: bool = False,
) -> LoadReport:
    """Turn ResolvedPaths into LoadReport (tools/skills/prompts). Themes omitted."""
    report = LoadReport(root=root, resolved=resolved)

    tools, ext_skills, ext_prompts, ext_diags, by_pkg = load_extension_resources(
        resolved.extensions, strict=strict
    )
    skills, skill_diags = load_skill_resources(resolved.skills)
    prompts, prompt_diags = load_prompt_resources(resolved.prompts)

    for skill in skills:
        matched = False
        for pkg in by_pkg.values():
            if skill.filePath.startswith(pkg.root):
                pkg.skills.append(skill)
                matched = True
                break
        if not matched:
            # create package shell from skill path if needed
            pass

    for res in resolved.skills + resolved.prompts:
        by_pkg.setdefault(
            res.metadata.source,
            LoadedPackage(name=res.metadata.source, root=res.metadata.baseDir or res.metadata.source),
        )

    report.tools = tools
    report.skills = [*skills, *ext_skills]
    report.prompts = [*prompts, *ext_prompts]
    report.diagnostics = [*ext_diags, *skill_diags, *prompt_diags]
    report.packages = list(by_pkg.values())
    return report


__all__ = [
    "load_extension_resources",
    "load_prompt_resources",
    "load_skill_resources",
    "materialize_resolved",
]
