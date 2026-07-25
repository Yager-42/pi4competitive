"""Pydantic v2 request/response DTOs for the FastAPI inbound adapter.

All ``extra="forbid"`` (feature F-A15 / F-A21). No pi_agent / pi_ai / aiosqlite
imports here (contract G2).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


class WorkflowTaskRequest(BaseModel):
    """``POST /tasks`` body (placeholder, coarse-defined — feature F-A15)."""

    model_config = ConfigDict(extra="forbid")

    # PLACEHOLDER: deep sub-structure deferred to the workflow feature.
    research_brief: dict[str, Any]
    competitor_discovery: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = ["PromptRequest", "SessionCreateRequest", "WorkflowTaskRequest"]
