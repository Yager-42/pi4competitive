"""Six-stage research workflow — STAGES + StageResult + minimal output schemas.

upstream reference: competitive-agent rr-refactor workflows/competitive/models.py
(structure isomorphic, behavior rewritten — feature research-workflow-v1 F-R1/F-R10).

Pure domain: no fastapi / aiosqlite / pi_agent / pi_ai imports (contract G1).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

# F-R1: six stages, isomorphic to legacy STAGES.
STAGES: tuple[str, ...] = ("plan", "collect", "analyze", "write", "review", "cite")

StageName = Literal["plan", "collect", "analyze", "write", "review", "cite"]
StageState = Literal["pending", "running", "ok", "failed"]

# F-R10: minimal per-stage output schema (required top-level keys).
# Agent prompts must produce JSON matching these; handler tolerates parse failure
# by falling back to a raw wrapper (stage still counts as ok if non-empty).
STAGE_OUTPUT_SCHEMA: dict[str, set[str]] = {
    "plan": {"plan"},
    "collect": {"evidence"},
    "analyze": {"analysis"},
    "write": {"report"},
    "review": {"verdict"},
    "cite": {"citations"},
}

# Dependencies: which prior stages must be ok before this one runs (F-R3).
STAGE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "plan": (),
    "collect": ("plan",),
    "analyze": ("collect",),
    "write": ("analyze",),
    "review": ("write",),
    "cite": ("write",),
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

    Returns a StageResult; ok=False if required keys missing.
    """
    required = STAGE_OUTPUT_SCHEMA.get(stage, set())
    missing = [k for k in required if k not in output]
    if missing:
        return StageResult(
            stage=stage,
            ok=False,
            output=output,
            error=f"missing required fields: {missing}",
        )
    # Non-empty check: required field must be truthy (plan text, evidence list, ...).
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
    """Initial projection for a task (F-R13)."""
    return {
        "current_stage": None,
        "stages": {name: "pending" for name in STAGES},
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
