"""Task value object + state machine (pure domain).

No fastapi / aiosqlite / pi_agent / pi_ai imports (contract G1, feature F-A25).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

TaskStatus = Literal["pending", "running", "aborted", "completed", "failed"]
TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset({"aborted", "completed", "failed"})

# Legal transitions (feature F-A16 / F-A18): placeholder runner flips pending→running→completed.
# abort may set non-terminal → aborted; failure → failed. Terminal states are sticky.
_LEGAL_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    "pending": frozenset({"running", "aborted", "failed"}),
    "running": frozenset({"completed", "aborted", "failed"}),
    "aborted": frozenset(),
    "completed": frozenset(),
    "failed": frozenset(),
}


class TaskStatusError(ValueError):
    """Raised on an illegal task status transition."""


@dataclass
class Task:
    """Research task projection value object (pure).

    ``session_id`` is None in the placeholder phase — the placeholder runner does
    not run an agent and therefore creates no JSONL session (feature F-A17).
    When a real workflow feature lands, the runner will create a session and
    populate this field.
    """

    task_id: str
    query: str
    status: TaskStatus = "pending"
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    projection: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: _now_iso())
    updated_at: str = field(default_factory=lambda: _now_iso())

    def transition(self, next_status: TaskStatus) -> None:
        """Apply a legal status transition or raise TaskStatusError.

        Terminal states are sticky: transitioning to the same terminal status is
        a no-op (so abort on an already-aborted/completed/failed task is safe —
        feature F-A18 boundary case).
        """
        if self.status == next_status:
            return
        if self.status in TERMINAL_STATUSES:
            raise TaskStatusError(
                f"task {self.task_id} is terminal ({self.status}); cannot move to {next_status}"
            )
        allowed = _LEGAL_TRANSITIONS[self.status]
        if next_status not in allowed:
            raise TaskStatusError(
                f"illegal transition {self.status} → {next_status} for task {self.task_id}"
            )
        self.status = next_status
        self.updated_at = _now_iso()

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def to_projection(self) -> dict[str, Any]:
        """Render the projection snapshot stored in ``projection_json``."""
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "query": self.query,
            "status": self.status,
            "metadata": dict(self.metadata),
            "projection": dict(self.projection),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = ["TERMINAL_STATUSES", "Task", "TaskStatus", "TaskStatusError"]
