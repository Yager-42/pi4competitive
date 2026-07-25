"""Research-brief request models (placeholder, coarse-defined).

PLACEHOLDER — research workflow is not frozen (Roadmap §0). These models only
validate top-level structure; they do NOT implement the legacy repo's
cross-field invariants (decisions-cover-candidates / context_fingerprint /
target consistency). Those land with a future workflow feature.

``research_brief`` and ``competitor_discovery`` are intentionally ``dict`` —
the deep sub-structure (target/goal/scope/candidates...) is not modeled here;
it will be defined when the workflow feature is frozen.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorkflowTaskRequest(BaseModel):
    """``POST /tasks`` request body (feature F-A15, coarse placeholder)."""

    model_config = ConfigDict(extra="forbid")

    research_brief: dict[str, Any] = Field(
        ..., description="Research brief payload (deep structure TBD with workflow feature)."
    )
    competitor_discovery: dict[str, Any] = Field(
        ..., description="Competitor discovery payload (deep structure TBD with workflow feature)."
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = ["WorkflowTaskRequest"]
