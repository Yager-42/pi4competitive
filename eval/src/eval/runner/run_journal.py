"""Eval-local RunJournal: JSONL event log per run.

Writes ``data/runs/<run_id>/events.jsonl`` with one RunEvent-shaped line per
event: ``{event_id, run_id, event_type, payload, created_at}`` — the same
schema as ``competitive_app.adapter.out.observability.run_journal.RunJournal``
so the operations collector reads A1 and A2 events with one format.

Kept in the eval package (not importing competitive_app) so the A1 service
stays decoupled: eval talks to apps over HTTP / standalone services, never
through package imports (基准文档 §4: adapter 属于评测外围).

A1 emits a subset of the whitelisted event types used by A2
(``agent.*``/``tool.*``/``llm.*``/``budget``); no secret payloads are written
(A1 tools take only search params, API keys stay in env).
"""

from __future__ import annotations

import json
import logging
import random
import string
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    """Return an ISO-8601 timestamp explicitly anchored to UTC."""
    return datetime.now(UTC).isoformat()


def _make_event_id() -> str:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")[:-3]  # ms precision
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"evt-{ts}-{suffix}"


class RunJournal:
    """Append-only JSONL event log for one A1 run."""

    def __init__(self, run_id: str, events_path: str | Path) -> None:
        self.run_id = run_id
        self.events_path = Path(events_path)

    def append(self, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "event_id": _make_event_id(),
            "run_id": self.run_id,
            "event_type": event_type,
            "payload": payload or {},
            "created_at": utc_now_iso(),
        }
        with self.events_path.open("a", encoding="utf-8") as file:
            # JSONL is line-oriented: each event must occupy exactly one line.
            file.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        return event

    def append_safe(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        """Append without raising: journal failure must never break the agent run."""
        try:
            self.append(event_type, payload)
        except Exception:
            logger.warning("journal append failed: %s", event_type, exc_info=True)


__all__ = ["RunJournal", "utc_now_iso"]
