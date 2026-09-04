"""Stage-level retry (P0-3): a transient stage failure must not kill the run.

A stalled stream or a schema miss is independent per attempt, so the runner
retries a bounded number of times. Aborts are decisions, not faults, and are
never retried.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from competitive_app.application.workflow.research_runner import (
    STAGE_MAX_ATTEMPTS,
    ResearchRunner,
)
from competitive_app.domain.stage import StageResult


def _runner(outcomes: list[Any]) -> tuple[ResearchRunner, list[dict[str, Any]]]:
    """A bare runner wired only for _run_stage_with_retry.

    Built with ``object.__new__`` on purpose: the retry loop touches just
    _run_stage/_emit_event/abort_signal, so constructing the full collaborator
    graph (agent, harness, session, engine) would test wiring, not retry.
    """
    runner = object.__new__(ResearchRunner)
    runner.task_id = "task-1"
    runner.abort_signal = asyncio.Event()
    events: list[dict[str, Any]] = []

    async def emit(event_type: str, payload: dict[str, Any]) -> None:
        events.append({"type": event_type, **payload})

    runner._emit_event = emit
    remaining = list(outcomes)

    async def run_stage(name: str, _projection: dict[str, Any]) -> StageResult:
        outcome = remaining.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome is True:
            return StageResult(stage=name, ok=True, output={"plan": "ok"})
        return StageResult(stage=name, ok=False, output={}, error=str(outcome))

    runner._run_stage = run_stage
    return runner, events


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Collapse the backoff so tests do not sleep through it."""
    monkeypatch.setattr(
        "competitive_app.application.workflow.research_runner"
        ".STAGE_RETRY_BASE_DELAY_SECONDS",
        0.0,
    )


@pytest.mark.asyncio
async def test_transient_failure_is_retried_and_succeeds() -> None:
    runner, events = _runner(["missing required fields: ['plan']", True])
    result = await runner._run_stage_with_retry("plan", {})
    assert result.ok is True
    retries = [e for e in events if e["type"] == "stage_retry"]
    assert len(retries) == 1
    assert retries[0]["attempt"] == 1
    assert "missing required fields" in retries[0]["error"]


@pytest.mark.asyncio
async def test_raised_exception_is_retried_not_propagated() -> None:
    runner, _ = _runner([TimeoutError("read timeout"), True])
    result = await runner._run_stage_with_retry("plan", {})
    assert result.ok is True


@pytest.mark.asyncio
async def test_gives_up_after_max_attempts_and_reports_last_error() -> None:
    runner, events = _runner(["boom"] * STAGE_MAX_ATTEMPTS)
    result = await runner._run_stage_with_retry("plan", {})
    assert result.ok is False
    assert result.error == "boom"
    # One retry event per gap between attempts, not one per attempt.
    assert len([e for e in events if e["type"] == "stage_retry"]) == STAGE_MAX_ATTEMPTS - 1


@pytest.mark.asyncio
async def test_cancellation_propagates_without_retry() -> None:
    runner, events = _runner([asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        await runner._run_stage_with_retry("plan", {})
    assert [e for e in events if e["type"] == "stage_retry"] == []


@pytest.mark.asyncio
async def test_aborted_stage_is_not_retried() -> None:
    runner, events = _runner(["aborted", True])
    runner.abort_signal.set()
    result = await runner._run_stage_with_retry("plan", {})
    assert result.ok is False
    assert [e for e in events if e["type"] == "stage_retry"] == []


@pytest.mark.asyncio
async def test_abort_during_backoff_stops_further_attempts() -> None:
    runner, events = _runner(["boom", True])

    original = runner._run_stage

    async def fail_then_abort(name: str, projection: dict[str, Any]) -> StageResult:
        result = await original(name, projection)
        runner.abort_signal.set()  # abort arrives while the stage is failing
        return result

    runner._run_stage = fail_then_abort
    result = await runner._run_stage_with_retry("plan", {})
    assert result.ok is False
    assert [e for e in events if e["type"] == "stage_retry"] == []
