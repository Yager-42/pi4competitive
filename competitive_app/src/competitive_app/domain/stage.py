"""Three-stage research workflow — STAGES + StageResult + minimal output schemas.

research-workflow-v1 v0.2.0 (ADR 0010 D-S2): six stages → three stages
(plan/search/write). analyze/cite职责并入 search/write, 不作为独立 stage。

Pure domain: no fastapi / aiosqlite / pi_agent / pi_ai imports (contract G1).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

# F-R25: three stages (was six in v0.1.1).
STAGES: tuple[str, ...] = ("plan", "search", "write")

StageName = Literal["plan", "search", "write"]
StageState = Literal["pending", "running", "ok", "failed"]

# F-R10: minimal per-stage output schema (required top-level keys).
# Agent prompts must produce JSON matching these; handler tolerates parse failure
# by falling back to a raw wrapper (stage still counts as ok if non-empty).
# search: `coverage` is required (the coverage snapshot); `evidence` may be empty
# when all cells were searched but yielded nothing (unknown) — search still counts
# as ok because the coverage map was driven to a terminal state.
STAGE_OUTPUT_SCHEMA: dict[str, set[str]] = {
    "plan": {"plan"},                        # + coverage_schema (validated in runner)
    "search": {"coverage"},                  # evidence is optional (may be empty)
    "write": {"report"},                     # markdown with citations
}

# Dependencies: which prior stages must be ok before this one runs (F-R3).
# stage 间严格顺序不回退; search 阶段内循环补搜不算回退 (ADR 0010 D-S8).
STAGE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "plan": (),
    "search": ("plan",),
    "write": ("search",),
}


@dataclass
class StageResult:
    """Result of running one stage."""

    stage: str
    ok: bool
    output: dict[str, Any]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "ok": self.ok, "output": self.output, "error": self.error}


def validate_stage_output(stage: str, output: dict[str, Any]) -> StageResult:
    """Validate a stage output dict against the minimal schema (F-R10).

    Returns a StageResult; ok=False if required keys missing or empty.
    """
    if stage not in STAGE_OUTPUT_SCHEMA:
        return StageResult(
            stage=stage,
            ok=False,
            output=output,
            error=f"unknown stage: {stage}",
        )
    required = STAGE_OUTPUT_SCHEMA.get(stage, set())
    missing = [k for k in required if k not in output]
    if missing:
        return StageResult(
            stage=stage,
            ok=False,
            output=output,
            error=f"missing required fields: {missing}",
        )
    # Non-empty check: required field must be truthy.
    for k in required:
        if not output.get(k):
            return StageResult(
                stage=stage,
                ok=False,
                output=output,
                error=f"empty required field: {k}",
            )
    return StageResult(stage=stage, ok=True, output=output)


def empty_projection() -> dict[str, Any]:
    """Initial projection for a task (F-R13). v0.2.0: 3 stages + coverage.

    v0.3.1: report card fields (report_title/brands/evidence_count/claim_count)
    filled by the runner when the task completes — used by GET /reports cards.
    """
    return {
        "current_stage": None,
        "stages": {name: "pending" for name in STAGES},
        "coverage": {"filled": 0, "total": 0, "pending_cells": 0},
        # v0.3.1 report card fields (populated on task completion).
        "report_title": None,
        "brands": [],
        "evidence_count": 0,
        "claim_count": 0,
    }


__all__ = [
    "STAGES",
    "STAGE_DEPENDENCIES",
    "STAGE_OUTPUT_SCHEMA",
    "StageName",
    "StageResult",
    "StageState",
    "empty_projection",
    "validate_stage_output",
]
