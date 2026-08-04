"""Skills resource loading semantics.

upstream: packages/agent/src/harness/skills.ts
"""
from __future__ import annotations
import html

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Skill:
    name: str
    description: str
    content: str
    filePath: str
    disableModelInvocation: bool = False


def format_skills_for_system_prompt(skills: list[Skill]) -> str:
    visible = [s for s in skills if not s.disableModelInvocation]
    if not visible:
        return ""
    lines = ["<skills>"]
    for s in visible:
        safe_name = html.escape(s.name, quote=True)
        safe_path = html.escape(s.filePath, quote=True)
        safe_description = html.escape(s.description, quote=True)
        lines.append(
            f'  <skill name="{safe_name}" path="{safe_path}">\n'
            f"    <description>{safe_description}</description>\n"
            f"  </skill>"
        )
    lines.append("</skills>")
    return "\n".join(lines)


def load_skill_from_file(path: str | Path) -> Skill:
    """Load a SKILL.md-style file: optional YAML frontmatter + body."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    name = p.stem
    description = ""
    content = text
    disable_model_invocation = False
    lines = text.splitlines(keepends=True)
    if lines and lines[0].rstrip("\r\n").strip() == "---":
        closing_index = next(
            (i for i, line in enumerate(lines[1:], start=1) if line.rstrip("\r\n").strip() == "---"),
            None,
        )
        if closing_index is not None:
            front = "".join(lines[1:closing_index])
            content = "".join(lines[closing_index + 1 :]).lstrip("\r\n")
            for line in front.splitlines():
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                k = k.strip().lower()
                v = v.strip().strip("\"'")
                if k == "name":
                    name = v
                elif k == "description":
                    description = v
                elif k == "disablemodelinvocation":
                    disable_model_invocation = v.lower() == "true"
    if not description:
        # first non-empty line as description fallback
        for line in content.splitlines():
            if line.strip():
                description = line.strip().lstrip("# ").strip()
    return Skill(
        name=name,
        description=description,
        content=content,
        filePath=str(p.resolve()),
        disableModelInvocation=disable_model_invocation,
    )


def load_skills_from_paths(paths: list[str | Path]) -> list[Skill]:
    skills: list[Skill] = []
    for path in paths:
        p = Path(path)
        if p.is_dir():
            for skill_md in sorted(p.rglob("SKILL.md")):
                skills.append(load_skill_from_file(skill_md))
        elif p.is_file():
            skills.append(load_skill_from_file(p))
    return skills


def skill_to_context_injection(skill: Skill) -> str:
    return f"# Skill: {skill.name}\n\n{skill.description}\n\n{skill.content}"


__all__ = [
    "Skill",
    "format_skills_for_system_prompt",
    "load_skill_from_file",
    "load_skills_from_paths",
    "skill_to_context_injection",
]
