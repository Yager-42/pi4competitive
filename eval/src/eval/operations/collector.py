"""operations_collector (D11 §12.5).

读 data/runs/<task_id>/events.jsonl (RunJournal) + task projection + SOCM,
产 operations.json: search/fetch 数, fallback 次数, terminal status,
coverage cells, distinct domains, evidence count, 失败阶段.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass
class OperationsResult:
    terminal_status: str = "unknown"
    failure_stage: str | None = None
    search_calls: int = 0
    fetch_calls: int = 0
    fallback_count: int = 0
    distinct_domains: int = 0
    evidence_count: int = 0
    coverage_filled: int = 0
    coverage_unknown: int = 0
    coverage_conflict: int = 0
    coverage_total: int = 0
    coverage_ratio: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SEARCH_TOOL_NAMES = {"tavily_search", "anysearch_search", "grok_search"}
_FETCH_TOOL_NAMES = {"tavily_fetch", "anysearch_fetch", "grok_fetch"}


def collect_operations(
    *,
    events_path: Path | str,
    projection: dict[str, Any],
    socm: dict[str, Any] | None,
) -> OperationsResult:
    result = OperationsResult()
    result.terminal_status = projection.get("status", "unknown")
    result.failure_stage = projection.get("first_non_ok_stage")
    domains: set[str] = set()

    p = Path(events_path)
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            et = evt.get("event_type", "")
            payload = evt.get("payload") or {}
            if et == "tool.called":
                name = payload.get("name", "")
                if name in _SEARCH_TOOL_NAMES:
                    result.search_calls += 1
                elif name in _FETCH_TOOL_NAMES:
                    result.fetch_calls += 1
            elif et == "tool.finished":
                url = payload.get("url") or payload.get("source")
                if url:
                    try:
                        domains.add(urlparse(url).netloc)
                    except Exception:
                        pass
            elif et.startswith("llm.fallback"):
                if et in ("llm.fallback_switch", "llm.fallback_start"):
                    result.fallback_count += 1

    result.distinct_domains = len(domains)

    if socm:
        result.coverage_filled = int(socm.get("filled", 0))
        result.coverage_unknown = int(socm.get("unknown", 0))
        result.coverage_conflict = int(socm.get("conflict", 0))
        result.coverage_total = int(socm.get("total", 0))
        result.coverage_ratio = float(socm.get("ratio", 0.0))
    # evidence_count from projection if available
    result.evidence_count = int(projection.get("evidence_count", 0))
    return result


__all__ = ["OperationsResult", "collect_operations"]
