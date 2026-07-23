"""System prompt assembly.

upstream: packages/agent/src/harness/system-prompt.ts
"""
from __future__ import annotations

from typing import Any

from .skills import Skill, format_skills_for_system_prompt


def build_system_prompt(
    *,
    base: str = "",
    skills: list[Skill] | None = None,
    extra_sections: list[str] | None = None,
) -> str:
    parts: list[str] = []
    if base:
        parts.append(base.strip())
    skills_block = format_skills_for_system_prompt(skills or [])
    if skills_block:
        parts.append(skills_block)
    for section in extra_sections or []:
        if section and section.strip():
            parts.append(section.strip())
    return "\n\n".join(parts)


__all__ = ["build_system_prompt"]
