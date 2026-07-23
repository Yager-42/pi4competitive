"""Skills resource loading semantics.

upstream: packages/agent/src/harness/skills.ts
"""
from __future__ import annotations

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
        lines.append(
            f'  <skill name="{s.name}" path="{s.filePath}">\n'
            f"    <description>{s.description}</description>\n"
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
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            front = parts[1]
            content = parts[2].lstrip("\n")
            for line in front.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    k = k.strip().lower()
                    v = v.strip().strip("\"'")
                    if k == "name":
                        name = v
                    elif k == "description":
                        description = v
    if not description:
        # first non-empty line as description fallback
        for line in content.splitlines():
            if line.strip():
                description = line.strip().lstrip("# ").strip()
                break
    return Skill(name=name, description=description, content=content, filePath=str(p.resolve()))


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
