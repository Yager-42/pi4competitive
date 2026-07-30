"""Workflow stage Skill composition host glue."""
from __future__ import annotations
from collections.abc import Iterable
from ...domain.evolution.skill_types import SkillRecord
from ...domain.evolution.workflow_scope import SkillScope
from .injector import compose_system_prompt

class StageSkillComposer:
    MAX_PER_SCOPE = 3
    def compose(self, base_prompt: str, skills: Iterable[SkillRecord], scope: SkillScope | None = None) -> str:
        return compose_system_prompt(base_prompt, list(skills)[: self.MAX_PER_SCOPE])
    def compose_system_prompt(self, base_prompt: str, skills: Iterable[SkillRecord], scope: SkillScope | None = None) -> str:
        return self.compose(base_prompt, skills, scope)
    def compose_for_scope(self, base_prompt: str, skills: Iterable[SkillRecord], scope: SkillScope) -> str:
        return self.compose(base_prompt, skills, scope)

__all__ = ["StageSkillComposer"]
