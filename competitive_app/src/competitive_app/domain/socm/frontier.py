"""SOCM Frontier Memory — task queue with priority + blocked_by DAG.

research-workflow-v1 v0.2.0 / ADR 0010. v0.2.0 has a single task type `fill`
(one entity × its empty cells); `backfill` hook reserved for future
multi-table feature (YAGNI now).

Pure domain (G1). Reference (architecture only): SearchOS searchos/socm/frontier.py.
SearchOS priority is 0-1 float (higher = more important); v0.2.0 uses the same
convention. Dequeue: ready tasks (blocked_by all terminal) sorted by
(-priority, created_at) — highest priority first, FIFO within priority.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# Backstop caps (SearchOS frontier.py:68). v0.2.0 keeps them generous.
MAX_FRONTIER_DEPTH = 5
MAX_FRONTIER_CAP = 200
MAX_TASK_ATTEMPTS = 3


class FrontierTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


_TERMINAL = {FrontierTaskStatus.COMPLETED, FrontierTaskStatus.CANCELLED}


class FrontierTask(BaseModel):
    """One dispatchable subtask (v0.2.0: always kind=fill)."""

    id: str
    question: str = ""              # short display text
    kind: str = "fill"              # v0.2.0: fill only; backfill reserved
    status: FrontierTaskStatus = FrontierTaskStatus.PENDING
    # 0-1 float; higher = more important (SearchOS convention).
    priority: float = 0.5
    parent_id: str = ""
    depth: int = 0
    # Task IDs this depends on; empty = ready.
    blocked_by: list[str] = Field(default_factory=list)
    # "entity.attribute" cell keys this task targets.
    target_cells: list[str] = Field(default_factory=list)
    table_id: str = ""
    assigned_agent_id: str = ""
    attempts: int = 0
    created_at: float = 0.0
    resolution: str = ""

    def is_terminal(self) -> bool:
        return self.status in _TERMINAL


class Frontier(BaseModel):
    """Task pool with priority + blocked_by DAG."""

    tasks: list[FrontierTask] = Field(default_factory=list)

    def add(self, task: FrontierTask) -> FrontierTask | None:
        """Enqueue a task. Returns the task (possibly existing if deduped), or
        None if rejected (depth > MAX or cap exceeded and not evictable)."""
        if task.depth > MAX_FRONTIER_DEPTH:
            return None
        # Dedup: same kind + same target_cells subset within active tasks.
        dup = self._find_duplicate(task)
        if dup is not None:
            if task.priority > dup.priority:
                dup.priority = task.priority
            return dup
        # Blocked if any dep is not terminal.
        if task.blocked_by and not self._deps_terminal(task):
            task.status = FrontierTaskStatus.BLOCKED
        self.tasks.append(task)
        self._evict_if_over_cap()
        return task

    def dequeue(self, done_ids: set[str] | None = None) -> FrontierTask | None:
        """Take the highest-priority ready PENDING task; flip to RUNNING.

        Ready = PENDING + blocked_by all in done_ids (or terminal) +
        attempts < MAX_TASK_ATTEMPTS.
        """
        done = done_ids or set()
        # A persisted/retried task at the cap must not remain misleadingly pending.
        for t in self.tasks:
            if t.status == FrontierTaskStatus.PENDING and t.attempts >= MAX_TASK_ATTEMPTS:
                t.status = FrontierTaskStatus.CANCELLED
        # Unblock tasks whose deps are now terminal.
        for t in self.tasks:
            if t.status == FrontierTaskStatus.BLOCKED and self._deps_terminal(t, done):
                t.status = FrontierTaskStatus.PENDING
        candidates = [
            t
            for t in self.tasks
            if t.status == FrontierTaskStatus.PENDING
            and t.attempts < MAX_TASK_ATTEMPTS
            and all(d in done or self._task_terminal(d) for d in t.blocked_by)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda t: (-t.priority, t.created_at))
        picked = candidates[0]
        picked.status = FrontierTaskStatus.RUNNING
        picked.attempts += 1
        return picked

    def resolve(self, task_id: str, resolution: str = "") -> bool:
        """Mark a task COMPLETED with a resolution note."""
        for t in self.tasks:
            if t.id == task_id:
                t.status = FrontierTaskStatus.COMPLETED
                t.resolution = resolution
                return True
        return False

    def retry(self, task_id: str) -> bool:
        """Reset a RUNNING task, or cancel it after the retry cap."""
        for t in self.tasks:
            if t.id == task_id and t.status == FrontierTaskStatus.RUNNING:
                if t.attempts >= MAX_TASK_ATTEMPTS:
                    t.status = FrontierTaskStatus.CANCELLED
                else:
                    t.status = FrontierTaskStatus.PENDING
                return True
        return False

    def cancel(self, task_id: str) -> bool:
        for t in self.tasks:
            if t.id == task_id:
                t.status = FrontierTaskStatus.CANCELLED
                return True
        return False

    def pending_count(self) -> int:
        return sum(
            1
            for t in self.tasks
            if t.status in {FrontierTaskStatus.PENDING, FrontierTaskStatus.RUNNING, FrontierTaskStatus.BLOCKED}
        )

    def resolved_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == FrontierTaskStatus.COMPLETED)

    # ------------------------------------------------------------------ helpers

    def _find_duplicate(self, task: FrontierTask) -> FrontierTask | None:
        """Subset-match by target_cells within active tasks of same kind/table."""
        if not task.target_cells:
            return None
        new_cells = frozenset(task.target_cells)
        for t in self.tasks:
            if t.status not in {
                FrontierTaskStatus.PENDING,
                FrontierTaskStatus.RUNNING,
                FrontierTaskStatus.BLOCKED,
            }:
                continue
            if t.kind != task.kind or t.table_id != task.table_id:
                continue
            if not t.target_cells:
                continue
            if (
                new_cells.issubset(frozenset(t.target_cells))
                or frozenset(t.target_cells).issubset(new_cells)
            ):
                return t
        return None

    def _deps_terminal(self, task: FrontierTask, done: set[str] | None = None) -> bool:
        done = done or set()
        return all(d in done or self._task_terminal(d) for d in task.blocked_by)

    def _task_terminal(self, task_id: str) -> bool:
        for t in self.tasks:
            if t.id == task_id:
                return t.is_terminal()
        # A missing prerequisite is unresolved, not terminal. Eviction and
        # restored partial state must never make dependents dispatchable.
        return False

    def _evict_if_over_cap(self) -> None:
        if len(self.tasks) <= MAX_FRONTIER_CAP:
            return
        # Never evict a pending prerequisite while an active dependent names it.
        protected_ids = {
            dep
            for t in self.tasks
            if t.status in {
                FrontierTaskStatus.PENDING,
                FrontierTaskStatus.RUNNING,
                FrontierTaskStatus.BLOCKED,
            }
            for dep in t.blocked_by
        }
        pending = [
            t
            for t in self.tasks
            if t.status == FrontierTaskStatus.PENDING and t.id not in protected_ids
        ]
        pending.sort(key=lambda t: (t.priority, t.created_at))
        evict = pending[: len(self.tasks) - MAX_FRONTIER_CAP]
        evict_ids = {t.id for t in evict}
        self.tasks = [t for t in self.tasks if t.id not in evict_ids]

    def to_projection(self) -> dict[str, Any]:
        return {
            "total": len(self.tasks),
            "pending": self.pending_count(),
            "resolved": self.resolved_count(),
        }


__all__ = [
    "MAX_FRONTIER_CAP",
    "MAX_FRONTIER_DEPTH",
    "MAX_TASK_ATTEMPTS",
    "Frontier",
    "FrontierTask",
    "FrontierTaskStatus",
]
