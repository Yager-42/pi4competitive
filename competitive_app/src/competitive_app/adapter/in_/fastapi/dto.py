"""Pydantic v2 request/response DTOs for the FastAPI inbound adapter.

All ``extra="forbid"`` (feature F-A15 / F-A21). No pi_agent / pi_ai / aiosqlite
imports here (contract G2).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ....domain.research_brief import ResearchBrief


class SessionCreateRequest(BaseModel):
    """``POST /sessions`` body. No ``max_turns`` (feature F-A21)."""

    model_config = ConfigDict(extra="forbid")

    model: str = ""
    system_prompt: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromptRequest(BaseModel):
    """``POST /sessions/{id}/prompt`` body."""

    model_config = ConfigDict(extra="forbid")

    content: Any


class SearchOverrides(BaseModel):
    """``POST /tasks`` optional per-task search hyperparameter overrides (v0.3.5).

    All fields optional; omitted/None → use env default (backward compatible).
    Out-of-range values are clamped by the service; type errors → ignored.
    """

    model_config = ConfigDict(extra="forbid")

    # No ge/le here — service clamps out-of-range (Q3); type errors ignored.
    max_parallel: int | None = None
    coverage_threshold: float | None = None
    max_queries: int | None = None
    max_wall_seconds: int | None = None


class WorkflowTaskRequest(BaseModel):
    """``POST /tasks`` body (research-workflow-v1 F-A15 v0.2.0).

    v0.3.3: overloaded — caller supplies exactly one of:
      - ``research_brief``: structured brief (legacy path, byte-identical behavior)
      - ``query``: free-form natural-language query → clarify flow
    The "exactly one" rule is enforced in the service (clearer error messages).
    v0.3.5: optional ``search_overrides`` — per-task search hyperparameters
    (override env SEARCH_* + Budget); persisted in metadata for resume (F-R16).
    """

    model_config = ConfigDict(extra="forbid")

    research_brief: ResearchBrief | None = None
    query: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    search_overrides: SearchOverrides | None = None


class ClarifyAnswer(BaseModel):
    """One answer to a clarify question (v0.3.3)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    value: str | list[str] = ""


class ClarifyRequest(BaseModel):
    """``POST /tasks/{task_id}/clarify`` body (v0.3.3)."""

    model_config = ConfigDict(extra="forbid")

    answers: list[ClarifyAnswer] = Field(default_factory=list)


class SubscriptionRequest(BaseModel):
    """``POST /subscriptions`` body (v0.3.3)."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    brands: list[str] = Field(default_factory=list)
    interval_hours: int = Field(default=24, ge=1)


class RefineRequest(BaseModel):
    """``POST /reports/{task_id}/refine`` body (v0.3.2)."""

    model_config = ConfigDict(extra="forbid")

    section_id: str = Field(description="Section id to rewrite (e.g. \"1\").")
    annotations: list[str] = Field(default_factory=list, description="User notes for the rewrite.")


class FeedbackRequest(BaseModel):
    """``POST /reports/{task_id}/feedback`` body (v0.3.2)."""

    model_config = ConfigDict(extra="forbid")

    edited_blocks: int = Field(ge=0, description="Blocks the user manually edited.")
    total_blocks: int = Field(ge=0, description="Total blocks in the report.")
    data: dict[str, Any] = Field(default_factory=dict, description="Extra feedback payload.")

    @model_validator(mode="after")
    def validate_block_counts(self) -> FeedbackRequest:
        if self.edited_blocks > self.total_blocks:
            raise ValueError("edited_blocks cannot exceed total_blocks")
        return self


__all__ = [
    "ClarifyAnswer",
    "ClarifyRequest",
    "FeedbackRequest",
    "PromptRequest",
    "RefineRequest",
    "SearchOverrides",
    "SessionCreateRequest",
    "SubscriptionRequest",
    "WorkflowTaskRequest",
]
