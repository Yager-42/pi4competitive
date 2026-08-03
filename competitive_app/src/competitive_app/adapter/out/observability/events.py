"""Run event dataclass.

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/journal/events.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see native/vendor/licenses/POIROT-MIT.txt)
Host delta: import path only (COPY 100%, plan P4-llm-fallback-observability §2).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

_CST = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class RunEvent:
    event_id: str
    run_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now_iso() -> str:
    return datetime.now(_CST).isoformat()
