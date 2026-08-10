"""operations_collector: events.jsonl + projection + SOCM -> operations.json (D11)."""

from __future__ import annotations

import json
from pathlib import Path

from eval.operations.collector import collect_operations


def _events_jsonl(path: Path, events: list[dict]):
    with path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def test_collect_counts_search_fetch_calls():
    events = [
        {"event_type": "agent.started"},
        {"event_type": "tool.called", "payload": {"name": "tavily_search"}},
        {"event_type": "tool.finished", "payload": {"name": "tavily_search"}},
        {"event_type": "tool.called", "payload": {"name": "tavily_fetch"}},
        {"event_type": "tool.called", "payload": {"name": "tavily_search"}},
        {"event_type": "llm.fallback_switch", "payload": {"from": "openai", "to": "openai"}},
        {"event_type": "agent.finished"},
    ]
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        ej = Path(d) / "events.jsonl"
        _events_jsonl(ej, events)
        result = collect_operations(
            events_path=ej,
            projection={"status": "completed", "first_non_ok_stage": None},
            socm={"filled": 10, "unknown": 2, "conflict": 1, "total": 15, "ratio": 0.66},
        )
        assert result.search_calls == 2
        assert result.fetch_calls == 1
        assert result.fallback_count == 1
        assert result.terminal_status == "completed"
        assert result.coverage_filled == 10
        assert result.coverage_total == 15


def test_collect_handles_missing_socm():
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        ej = Path(d) / "events.jsonl"
        _events_jsonl(ej, [{"event_type": "agent.started"}])
        result = collect_operations(events_path=ej, projection={"status": "failed"}, socm=None)
        assert result.terminal_status == "failed"
        assert result.coverage_total == 0  # A1: no SOCM


def test_collect_distinct_domains():
    events = [
        {
            "event_type": "tool.finished",
            "payload": {"name": "tavily_fetch", "url": "https://a.com/x"},
        },
        {
            "event_type": "tool.finished",
            "payload": {"name": "tavily_fetch", "url": "https://a.com/y"},
        },
        {
            "event_type": "tool.finished",
            "payload": {"name": "tavily_fetch", "url": "https://b.com/z"},
        },
    ]
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        ej = Path(d) / "events.jsonl"
        _events_jsonl(ej, events)
        result = collect_operations(events_path=ej, projection={"status": "completed"}, socm={})
        assert result.distinct_domains == 2
