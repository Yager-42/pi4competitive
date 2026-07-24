"""Apply loaded capability tools/skills onto a P2 Agent.

Collision policy: first-wins (existing Agent tools keep priority).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from earendil_works.pi_agent.types import AgentTool
from earendil_works.pi_agent.extensions import attach_extension_runtime
from earendil_works.pi_agent.harness.system_prompt import build_system_prompt

from .types import LoadReport, ResourceDiagnostic

if TYPE_CHECKING:
    from earendil_works.pi_agent.agent import Agent

CollisionPolicy = Literal["first_wins", "replace"]


def merge_tools(
    existing: list[AgentTool],
    incoming: list[AgentTool],
    *,
    policy: CollisionPolicy = "first_wins",
) -> tuple[list[AgentTool], list[ResourceDiagnostic]]:
    diags: list[ResourceDiagnostic] = []
    if policy == "replace":
        by_name = {t.name: t for t in existing}
        for tool in incoming:
            if tool.name in by_name:
                diags.append(
                    ResourceDiagnostic(
                        level="info",
                        package=None,
                        path=None,
                        message=f"tool replaced: {tool.name}",
                    )
                )
            by_name[tool.name] = tool
        return list(by_name.values()), diags

    # first_wins
    seen = {t.name for t in existing}
    out = list(existing)
    for tool in incoming:
        if tool.name in seen:
            diags.append(
                ResourceDiagnostic(
                    level="warn",
                    package=None,
                    path=None,
                    message=f"tool name collision skipped: {tool.name}",
                )
            )
            continue
        seen.add(tool.name)
        out.append(tool)
    return out, diags


def apply_capability_report(
    agent: Agent,
    report: LoadReport,
    *,
    policy: CollisionPolicy = "first_wins",
) -> list[ResourceDiagnostic]:
    """Attach the report runtime, tools, skills, and prompts to one Agent."""
    if report.extension_result is None:
        return []
    _merged, diags = merge_tools(list(agent.state.tools), list(report.tools), policy=policy)
    report.extension_runner = attach_extension_runtime(
        agent, report.extension_result, str(report.root), replace=policy == "replace"
    )
    agent.skills = list(report.skills)
    agent.prompts = list(report.prompts)
    agent.state.systemPrompt = build_system_prompt(base=agent.state.systemPrompt, skills=agent.skills)
    report.diagnostics.extend(diags)
    return diags


__all__ = ["CollisionPolicy", "apply_capability_report", "merge_tools"]
