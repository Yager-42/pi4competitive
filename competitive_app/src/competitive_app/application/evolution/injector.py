"""Skill injection adapted from Poirot ``skill/injector.py``.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/injector.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: Pi ``Skill``/``skill_to_context_injection`` replace LangChain
SystemMessage. Complete bodies are retained; file failures degrade to empty
body without breaking the workflow.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from earendil_works.pi_agent.harness.skills import Skill, skill_to_context_injection

from ...domain.evolution.skill_types import SkillRecord


def _read_body(path: str) -> str:
    try:
        content = Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].lstrip("\r\n")
    return content


def record_to_pi_skill(record: SkillRecord) -> Skill:
    return Skill(
        name=record.name,
        description=record.description,
        content=_read_body(record.path),
        filePath=str(Path(record.path).resolve()),
    )


def build_injection_text(skills: Iterable[SkillRecord]) -> str:
    records = list(skills)
    if not records:
        return ""
    return "\n\n".join(skill_to_context_injection(record_to_pi_skill(record)) for record in records)


def compose_system_prompt(base_prompt: str, skills: Iterable[SkillRecord]) -> str:
    injection = build_injection_text(skills)
    return f"{base_prompt}\n\n{injection}" if injection else base_prompt


__all__ = ["record_to_pi_skill", "build_injection_text", "compose_system_prompt"]
