"""Research-brief request models (research-workflow-v1 F-R6).

Simplified from legacy competitive-agent ResearchBrief: keeps only what the
``plan`` stage needs. Drops breadth/depth/evidence_policy/chart_requirements/
competitor_decisions (legacy bound to unfrozen report schema).

Pure domain: no fastapi / aiosqlite / pi_agent / pi_ai imports (contract G1).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TargetIdentity(BaseModel):
    """Research target identity (minimal)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", description="Target product/company name.")
    category: str = Field(default="", description="Target category description.")


class ResearchBrief(BaseModel):
    """Simplified research brief (F-R6)."""

    model_config = ConfigDict(extra="forbid")

    target: TargetIdentity
    goal: str = Field(min_length=1, description="Research goal in natural language.")
    competitors: list[str] = Field(min_length=1, description="Competitor names (>=1).")
    dimensions: list[str] = Field(min_length=1, description="Research dimensions, e.g. pricing/features.")


class WorkflowTaskRequest(BaseModel):
    """``POST /tasks`` request body (feature F-A15 v0.2.0)."""

    model_config = ConfigDict(extra="forbid")

    research_brief: ResearchBrief
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = ["ResearchBrief", "TargetIdentity", "WorkflowTaskRequest"]
