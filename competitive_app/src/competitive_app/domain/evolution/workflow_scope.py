"""Pure workflow scope values and evidence references.

NEW-HOST module required by workflow-skill-self-evolution-v1. No IO, DB, FS,
Pi or LLM imports are permitted here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SkillScope = Literal["plan", "search", "extraction", "write"]
SCOPES: tuple[SkillScope, ...] = ("plan", "search", "extraction", "write")


@dataclass(frozen=True)
class WorkflowScope:
    value: SkillScope

    def __post_init__(self) -> None:
        if self.value not in SCOPES:
            raise ValueError(f"invalid workflow scope: {self.value!r}")

    @classmethod
    def from_str(cls, value: str) -> "WorkflowScope":
        return cls(value)  # type: ignore[arg-type]

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class EvidenceRef:
    """De-identified pointer to evidence held by JSONL/SOCM/App projections."""

    kind: str
    ref: str
    excerpt: str = ""


@dataclass(frozen=True)
class ProblemSignature:
    signature: str
    scope: SkillScope
    evidence_refs: tuple[EvidenceRef, ...] = ()


__all__ = ["SkillScope", "SCOPES", "WorkflowScope", "EvidenceRef", "ProblemSignature"]
