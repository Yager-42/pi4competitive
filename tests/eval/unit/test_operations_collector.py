"""operations_collector: events.jsonl + projection + SOCM -> operations.json (D11)."""

from __future__ import annotations

import json
from pathlib import Path

from eval.operations.collector import collect_operations, extract_urls_from_details


def _events_jsonl(path: Path, events: list[dict]):
    with path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def _collect(events: list[dict], projection: dict | None = None, socm: dict | None = None):
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        ej = Path(d) / "events.jsonl"
        _events_jsonl(ej, events)
        return collect_operations(
            events_path=ej,
            projection=projection or {"status": "completed"},
            socm=socm,
        )


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
    result = _collect(
        events,
        socm={"filled": 10, "unknown": 2, "conflict": 1, "total": 15, "ratio": 0.66},
    )
    assert result.search_calls == 2
    assert result.fetch_calls == 1
    assert result.fallback_count == 1
    assert result.terminal_status == "completed"
    assert result.coverage_filled == 10
    assert result.coverage_total == 15
    # tool.finished without status -> counts as ok
    assert result.tool_calls_total == 1
    assert result.tool_calls_ok == 1
    assert result.tool_calls_error == 0
    assert result.tool_success_rate == 1.0


def test_collect_handles_missing_socm():
    result = _collect([{"event_type": "agent.started"}], projection={"status": "failed"})
    assert result.terminal_status == "failed"
    assert result.coverage_total == 0  # A1: no SOCM


def test_collect_distinct_domains():
    events = [
        {"event_type": "tool.finished", "payload": {"name": "tavily_fetch", "url": "https://a.com/x"}},
        {"event_type": "tool.finished", "payload": {"name": "tavily_fetch", "url": "https://a.com/y"}},
        {"event_type": "tool.finished", "payload": {"name": "tavily_fetch", "url": "https://b.com/z"}},
    ]
    result = _collect(events)
    assert result.distinct_domains == 2
    # evidence falls back to observed source URLs
    assert result.evidence_count == 3


def test_collect_journal_bridge_payload_key():
    """A2 journal_bridge 用 payload.tool_name（非 name）。"""
    events = [
        {"event_type": "tool.called", "payload": {"tool_name": "tavily_search"}},
        {"event_type": "tool.finished", "payload": {"tool_name": "tavily_search", "status": "ok"}},
    ]
    result = _collect(events)
    assert result.search_calls == 1
    assert result.tool_calls_ok == 1


def test_collect_tool_success_rate():
    events = [
        {"event_type": "tool.called", "payload": {"tool_name": "tavily_search"}},
        {"event_type": "tool.finished", "payload": {"tool_name": "tavily_search", "status": "ok"}},
        {"event_type": "tool.called", "payload": {"tool_name": "tavily_fetch"}},
        {"event_type": "tool.finished", "payload": {"tool_name": "tavily_fetch", "status": "ok"}},
        {"event_type": "tool.called", "payload": {"tool_name": "tavily_fetch"}},
        {"event_type": "tool.finished", "payload": {"tool_name": "tavily_fetch", "status": "error"}},
        # non-search tool
        {"event_type": "tool.called", "payload": {"tool_name": "echo_example"}},
        {"event_type": "tool.finished", "payload": {"tool_name": "echo_example", "status": "ok"}},
        # budget exhausted -> counts as error (A1 wrapper emits status=error)
        {"event_type": "tool.called", "payload": {"tool_name": "tavily_search"}},
        {"event_type": "tool.finished", "payload": {"tool_name": "tavily_search", "status": "budget_exhausted"}},
    ]
    result = _collect(events)
    assert result.tool_calls_total == 5
    assert result.tool_calls_ok == 3
    assert result.tool_calls_error == 2
    assert result.tool_success_rate == 0.6
    assert result.other_tool_calls == 1


def test_collect_usage_and_cost():
    events = [
        {
            "event_type": "llm.response",
            "payload": {
                "model": "deepseek-v3.2",
                "status": "ok",
                "usage": {
                    "input": 100,
                    "output": 50,
                    "cacheRead": 10,
                    "cacheWrite": 5,
                    "cost": {"total": 0.00123},
                },
            },
        },
        {
            "event_type": "llm.response",
            "payload": {
                "model": "deepseek-v3.2",
                "status": "error",
                "usage": {"input": 20, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            },
        },
    ]
    result = _collect(events)
    assert result.prompt_tokens == 100 + 10 + 20  # input + cacheRead
    assert result.completion_tokens == 50 + 5
    assert result.total_tokens == 185
    assert abs(result.cost - 0.00123) < 1e-9


def test_collect_timing_from_created_at():
    events = [
        {"event_type": "agent.started", "created_at": "2026-08-17T10:00:00+00:00"},
        {"event_type": "agent.finished", "created_at": "2026-08-17T10:01:30.250+00:00"},
    ]
    result = _collect(events)
    assert result.run_started_at == "2026-08-17T10:00:00+00:00"
    assert result.run_finished_at == "2026-08-17T10:01:30.250+00:00"
    assert result.duration_seconds == 90.25


def test_collect_urls_from_payload_details():
    events = [
        {
            "event_type": "tool.finished",
            "payload": {
                "tool_name": "tavily_search",
                "status": "ok",
                "urls": ["https://a.com/1", "https://a.com/2"],
            },
        },
        {
            "event_type": "tool.finished",
            "payload": {
                "tool_name": "tavily_fetch",
                "status": "ok",
                "details": {"url": "https://b.com/page"},
            },
        },
    ]
    result = _collect(events)
    assert result.distinct_domains == 2
    assert result.evidence_count == 3


def test_extract_urls_from_details():
    details = {
        "schema_version": "search_result.v1",
        "hits": [
            {"url": "https://a.com/x", "title": "X"},
            {"url": "https://a.com/y", "title": "Y"},
            {"title": "no url"},
        ],
    }
    assert extract_urls_from_details(details) == ["https://a.com/x", "https://a.com/y"]
    assert extract_urls_from_details({"url": "https://b.com/z"}) == ["https://b.com/z"]
    assert extract_urls_from_details({"hits": "not-a-list"}) == []
    assert extract_urls_from_details(None) == []


def test_collect_duration_prefers_stage_window_over_contaminated_tail():
    """A2 journals accumulate late harness events (agent.*/llm.*) from later
    tasks; duration must come from the task stage window, not the raw min/max."""
    events = [
        {"event_type": "task.stage_start", "payload": {"stage": "plan"}, "created_at": "2026-08-17T10:00:00+00:00"},
        {"event_type": "tool.called", "payload": {"name": "tavily_search"}, "created_at": "2026-08-17T10:01:00+00:00"},
        {"event_type": "task.stage_end", "payload": {"stage": "search"}, "created_at": "2026-08-17T10:02:00+00:00"},
        {"event_type": "task.stage_end", "payload": {"stage": "write"}, "created_at": "2026-08-17T10:04:00+00:00"},
        # contaminated tail: late agent events from a later task (raw min/max would span these)
        {"event_type": "agent.started", "created_at": "2026-08-17T12:00:00+00:00"},
        {"event_type": "agent.finished", "created_at": "2026-08-17T12:30:00+00:00"},
    ]
    result = _collect(events)
    assert result.duration_seconds == 240.0  # 10:04 - 10:00, not the 2.5h raw span
    assert result.run_started_at.startswith("2026-08-17T10:00:00")
    assert result.run_finished_at.startswith("2026-08-17T10:04:00")


def test_collect_duration_agent_lifecycle_when_no_stage():
    """A1 has no stage events; agent.started/finished define the window."""
    events = [
        {"event_type": "agent.started", "created_at": "2026-08-17T10:00:00+00:00"},
        {"event_type": "llm.request", "created_at": "2026-08-17T10:00:30+00:00"},
        {"event_type": "agent.finished", "created_at": "2026-08-17T10:01:30.250+00:00"},
    ]
    result = _collect(events)
    assert result.duration_seconds == 90.25
    assert result.run_finished_at == "2026-08-17T10:01:30.250+00:00"
