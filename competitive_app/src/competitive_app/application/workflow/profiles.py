"""Per-stage profiles + system prompts (research-workflow-v1 F-R20).

Hardcoded in code (not capability prompts resources). Each StageProfile binds a
system prompt and a tool-name filter. collect/cite use ``tool_names=None`` to
mean "dynamically pick loaded search tools (*_search / *_fetch)" (F-R19).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ...domain.stage import STAGES

StageName = Literal["plan", "collect", "analyze", "write", "review", "cite"]


@dataclass
class StageProfile:
    name: str
    system_prompt: str
    # None = dynamic search tools; [] = no tools; list = explicit names.
    tool_names: list[str] | None = field(default=None)


# --- system prompts (F-R20) -------------------------------------------------

_PLAN_PROMPT = """\
You are a research planner. Given the research brief, produce a concise collection
plan: which competitors to search, which dimensions to cover, and suggested search
queries. Output ONLY valid JSON: {"plan": "<markdown plan string>"}.
"""

_COLLECT_PROMPT = """\
You are an evidence collector. Use the available search tools to gather evidence
for the research plan. Call search tools as needed; you may make multiple calls.
After collecting, output ONLY valid JSON: {"evidence": [{"source": "<url or tool>", "content": "<finding>"}]}.
"""

_ANALYZE_PROMPT = """\
You are a competitive analyst. Given the collected evidence, analyze the
competitors across the requested dimensions. Note any evidence gaps. Output ONLY
valid JSON: {"analysis": "<markdown analysis>", "gaps": ["<gap description>"]}.
"""

_WRITE_PROMPT = """\
You are a research report writer. Given the analysis, write a structured markdown
report covering the target and each competitor across the requested dimensions.
Output ONLY valid JSON: {"report": "<markdown report string>"}.
"""

_REVIEW_PROMPT = """\
You are a research reviewer. Read the report and evaluate its quality, accuracy,
and completeness. Output ONLY valid JSON: {"verdict": "<approve|issues>", "issues": ["<issue>"]}.
"""

_CITE_PROMPT = """\
You are a citation specialist. Given the report and collected evidence, map key
claims to their sources. Output ONLY valid JSON: {"citations": [{"claim": "<claim text>", "source": "<url or tool>"}]}.
"""

_PROMPTS: dict[str, str] = {
    "plan": _PLAN_PROMPT,
    "collect": _COLLECT_PROMPT,
    "analyze": _ANALYZE_PROMPT,
    "write": _WRITE_PROMPT,
    "review": _REVIEW_PROMPT,
    "cite": _CITE_PROMPT,
}


def build_profiles() -> dict[str, StageProfile]:
    """Build the six stage profiles (F-R20)."""
    profiles: dict[str, StageProfile] = {}
    for name in STAGES:
        tool_names: list[str] | None = [] if name in {"plan", "analyze", "write", "review"} else None
        profiles[name] = StageProfile(name=name, system_prompt=_PROMPTS[name], tool_names=tool_names)
    return profiles


def is_search_tool(name: str) -> bool:
    """F-R19: a tool is a search tool if its name ends with _search or _fetch."""
    return name.endswith("_search") or name.endswith("_fetch")


__all__ = ["StageName", "StageProfile", "build_profiles", "is_search_tool"]
