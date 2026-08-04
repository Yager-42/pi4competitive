"""Load resolved local resources into runtime objects.

upstream: packages/coding-agent/src/core/resource-loader.ts (local load intent)
themes / TUI omitted.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from earendil_works.pi_agent.extensions import ExtensionRunner, load_extensions, wrap_registered_tools
from earendil_works.pi_agent.harness.prompt_templates import PromptTemplate
from earendil_works.pi_agent.harness.skills import Skill, load_skill_from_file

from .types import LoadReport, LoadedPackage, ResolvedPaths, ResolvedResource, ResourceDiagnostic


def load_skill_resources(resources: list[ResolvedResource]) -> tuple[list[Skill], list[ResourceDiagnostic]]:
    skills: list[Skill] = []
    diagnostics: list[ResourceDiagnostic] = []
    for resource in resources:
        if not resource.enabled:
            continue
        try:
            path = Path(resource.path)
            if not path.is_file():
                raise FileNotFoundError(path)
            skills.append(load_skill_from_file(path))
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(ResourceDiagnostic("error", resource.metadata.source, resource.path,
                                                  f"failed to load skill: {exc}"))
    return skills, diagnostics


def _load_prompt_resources_with_sources(
    resources: list[ResolvedResource],
) -> tuple[list[PromptTemplate], list[ResourceDiagnostic], list[tuple[PromptTemplate, ResolvedResource]]]:
    prompts: list[PromptTemplate] = []
    diagnostics: list[ResourceDiagnostic] = []
    loaded: list[tuple[PromptTemplate, ResolvedResource]] = []
    for resource in resources:
        if not resource.enabled:
            continue
        try:
            path = Path(resource.path)
            text = path.read_text(encoding="utf-8")
            name, description = path.stem, None
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    text = parts[2].lstrip("\n")
                    for line in parts[1].splitlines():
                        if ":" not in line:
                            continue
                        key, value = line.split(":", 1)
                        value = value.strip().strip("\"'")
                        if key.strip().lower() == "name":
                            name = value
                        elif key.strip().lower() == "description":
                            description = value
            prompt = PromptTemplate(name, text, description)
            prompts.append(prompt)
            loaded.append((prompt, resource))
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(ResourceDiagnostic("error", resource.metadata.source, resource.path,
                                                  f"failed to load prompt: {exc}"))
    return prompts, diagnostics, loaded


def load_prompt_resources(
    resources: list[ResolvedResource],
) -> tuple[list[PromptTemplate], list[ResourceDiagnostic]]:
    prompts, diagnostics, _ = _load_prompt_resources_with_sources(resources)
    return prompts, diagnostics


async def materialize_resolved_async(
    resolved: ResolvedPaths, *, root: Path, strict: bool = False
) -> LoadReport:
    report = LoadReport(root=root, resolved=resolved)
    enabled_extensions = [resource for resource in resolved.extensions if resource.enabled]
    result = await load_extensions([resource.path for resource in enabled_extensions], root)
    runner = ExtensionRunner.from_load_result(result, root)
    report.extension_result = result
    report.extension_runner = runner
    report.tools = wrap_registered_tools(runner.get_all_registered_tools(), runner)

    metadata = {str(Path(resource.path).resolve()): resource.metadata for resource in enabled_extensions}
    packages: dict[str, LoadedPackage] = {}
    for extension in result.extensions:
        info = metadata.get(str(Path(extension.resolvedPath).resolve()))
        if info is None:
            continue
        package = packages.setdefault(info.source, LoadedPackage(info.source, info.baseDir or info.source))
        package.tools.extend(
            wrap_registered_tools(list(extension.tools.values()), runner)
        )
    for error in result.errors:
        path = str(Path(error["path"]).resolve())
        info = metadata.get(path)
        report.diagnostics.append(ResourceDiagnostic("error", info.source if info else None,
                                                     error["path"], error["error"]))
    if strict and result.errors:
        from .errors import PackageLoadError
        raise PackageLoadError(result.errors[-1]["error"])

    skills, skill_diagnostics = load_skill_resources(resolved.skills)
    prompts, prompt_diagnostics, prompt_sources = _load_prompt_resources_with_sources(resolved.prompts)
    report.skills = skills
    report.prompts = prompts
    report.diagnostics.extend([*skill_diagnostics, *prompt_diagnostics])

    for resource in resolved.skills + resolved.prompts:
        if resource.enabled:
            packages.setdefault(
                resource.metadata.source,
                LoadedPackage(resource.metadata.source,
                              resource.metadata.baseDir or resource.metadata.source),
            )
    for skill in skills:
        for package in packages.values():
            if skill.filePath.startswith(package.root):
                package.skills.append(skill)
                break
    for prompt, resource in prompt_sources:
        packages[resource.metadata.source].prompts.append(prompt)
    report.packages = list(packages.values())
    return report


def materialize_resolved(
    resolved: ResolvedPaths, *, root: Path, strict: bool = False
) -> LoadReport:
    return asyncio.run(materialize_resolved_async(resolved, root=root, strict=strict))


__all__ = [
    "load_prompt_resources", "load_skill_resources", "materialize_resolved",
    "materialize_resolved_async",
]
