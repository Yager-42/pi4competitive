"""Per-stage profiles + system prompts (research-workflow-v1 v0.2.0 F-R20).

Three stages (plan/search/write). Each StageProfile binds a system prompt and
a tool-name filter. search uses ``tool_names=None`` to mean "dynamically pick
loaded search tools (*_search / *_fetch)" (F-R19). plan also gets search tools
for hub-page探测; write gets none (reads SOCM).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ...domain.stage import STAGES

StageName = Literal["plan", "search", "write"]


@dataclass
class StageProfile:
    name: str
    system_prompt: str
    # None = dynamic search tools; [] = no tools; list = explicit names.
    tool_names: list[str] | None = field(default=None)


# --- system prompts (F-R20) -------------------------------------------------

_PLAN_PROMPT = """\
You are a research planner for competitive analysis. Given the research brief \
(target + competitors + dimensions), produce a search plan, a coverage schema \
(entity × attribute table), and TYPED search queries per entity.

The coverage schema expands each brief dimension into concrete attribute \
columns. For example, "pricing" might expand to free_tier / paid_start_price / \
billing_unit; "features" might expand to real_time_collab / api_access. \
Choose attributes that meaningfully distinguish the competitors. Each \
attribute has a closed type: text / money_usd / bool / number / enum:<values>.

For EACH entity, also provide 3-5 TYPED search queries that target authoritative \
sources (official site/spec page, reputable review/media, parameter/compare \
pages). Prefer queries likely to land on the entity's official domain and major \
tech-media/parameter sites over generic aggregator pages. Also list source_hints \
(domains or site names known to carry authoritative data for this entity, e.g. \
"gsmarena.com", "the official manufacturer site", "ithome.com").

Output ONLY valid JSON:
{
  "plan": "<markdown: which competitors, which dimensions, overview of approach>",
  "coverage_schema": {
    "table_id": "t_competitive",
    "entities": [{"id": "e_<slug>", "name": "<name>", "kind": "target|competitor"}],
    "attributes": [{"id": "a_<slug>", "name": "<label>", "dimension": "<from brief>", "type": "<text|money_usd|bool|number|enum:v1,v2>", "validation": "non_empty"}]
  },
  "queries": [
    {"entity_id": "e_<slug>", "queries": ["<typed query 1>", "<typed query 2>", "..."], "source_hints": ["<domain or site>", "..."]}
  ]
}

The target must be one entity; every competitor must be an entity. At least one \
attribute per dimension. Attribute ids must be unique. The `queries` array must \
have one entry per entity. Typed queries and source_hints are critical — they \
guide the search sub-agents to authoritative sources.
"""

_SEARCH_PROMPT = """\
You are a search sub-agent for competitive research. You are given one \
subtask: fill specific empty cells (entity × attribute) of a coverage map by \
searching the web. Use the available search tools (*_search) to find pages, \
then fetch relevant pages (*_fetch) to read them. Make multiple calls as needed.

Your job is to FIND pages and let the extraction layer pull structured values — \
you do not need to output the values yourself. When you believe you have \
opened enough pages for this subtask, output ONLY valid JSON:
{"evidence": [{"source": "<url>", "content": "<brief finding or page summary>"}]}

If you cannot find evidence after reasonable effort, return {"evidence": []} \
with an empty list — do not fabricate values.
"""

_WRITE_PROMPT = """\
You are a research report writer. You are given a coverage map snapshot \
(entity × attribute table) where each cell is filled (with value + source), \
unknown (searched, no reliable source), or conflict (multiple disagreeing \
sources). Write a structured markdown report comparing the target and each \
competitor across the dimensions.

Render the coverage as a markdown table. Each fact must carry a citation \
marker [n] anchored to its source. List all sources at the end under a \
"## Sources" heading. For unknown cells, write "未找到可靠来源". For conflict \
cells, note the disagreement and pick the higher-confidence value.

Output ONLY valid JSON: {"report": "<markdown report string>"}.
"""

_PROMPTS: dict[str, str] = {
    "plan": _PLAN_PROMPT,
    "search": _SEARCH_PROMPT,
    "write": _WRITE_PROMPT,
}


def build_profiles() -> dict[str, StageProfile]:
    """Build the three stage profiles (F-R20)."""
    profiles: dict[str, StageProfile] = {}
    for name in STAGES:
        # plan + search: dynamic search tools; write: no tools (reads SOCM).
        tool_names: list[str] | None = None if name in {"plan", "search"} else []
        profiles[name] = StageProfile(name=name, system_prompt=_PROMPTS[name], tool_names=tool_names)
    return profiles


def is_search_tool(name: str) -> bool:
    """F-R19: a tool is a search tool if its name ends with _search or _fetch."""
    return name.endswith("_search") or name.endswith("_fetch")


__all__ = ["StageName", "StageProfile", "build_profiles", "is_search_tool"]
