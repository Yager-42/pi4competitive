"""A1 journal instrumentation: _wrap_tools_with_journal + EvalJournalStream.

验证 A1 的 tool/llm/agent 事件落盘（RunJournal schema），使 operations
collector 在 A1 上产出真实 search/fetch/成功率/URL/token 指标（D11 §12.5）。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from eval.runner.journal_stream import (
    EvalJournalStream,
    _sanitize_context,
    _sanitize_options,
)
from eval.runner.run_journal import RunJournal
from eval.runner.single_agent_app import _wrap_tools_with_journal


def _read_events(journal: RunJournal) -> list[dict]:
    events: list[dict] = []
    for line in journal.events_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def test_wrap_tools_emits_called_finished_with_urls(tmp_path):
    journal = RunJournal("run-1", tmp_path / "runs" / "run-1" / "events.jsonl")

    async def execute(tool_call_id, params, signal=None, on_update=None):
        return {
            "content": [{"type": "text", "text": "..."}],
            "details": {"hits": [{"url": "https://a.com/1"}]},
        }

    tool = SimpleNamespace(name="tavily_search", execute=execute)
    (wrapped,) = _wrap_tools_with_journal([tool], journal)

    async def run():
        await wrapped.execute("id", {"query": "x"})

    asyncio.run(run())

    events = _read_events(journal)
    assert [e["event_type"] for e in events] == ["tool.called", "tool.finished"]
    assert events[0]["payload"]["tool_name"] == "tavily_search"
    assert events[0]["payload"]["tool_input"] == {"query": "x"}
    assert events[1]["payload"]["status"] == "ok"
    assert events[1]["payload"]["urls"] == ["https://a.com/1"]


def test_wrap_tools_emits_error_status_on_exception(tmp_path):
    journal = RunJournal("run-2", tmp_path / "runs" / "run-2" / "events.jsonl")

    async def execute(tool_call_id, params, signal=None, on_update=None):
        raise RuntimeError("boom")

    tool = SimpleNamespace(name="tavily_search", execute=execute)
    (wrapped,) = _wrap_tools_with_journal([tool], journal)

    async def run():
        with pytest.raises(RuntimeError):
            await wrapped.execute("id", {})

    asyncio.run(run())

    events = _read_events(journal)
    assert events[1]["payload"]["status"] == "error"
    assert "boom" in events[1]["payload"]["error"]


def test_wrap_tools_emits_budget_event_on_exhaustion(tmp_path):
    journal = RunJournal("run-3", tmp_path / "runs" / "run-3" / "events.jsonl")

    async def execute(tool_call_id, params, signal=None, on_update=None):
        return {"content": [], "details": {"budget_exhausted": True, "kind": "search"}}

    tool = SimpleNamespace(name="tavily_search", execute=execute)
    (wrapped,) = _wrap_tools_with_journal([tool], journal)

    async def run():
        await wrapped.execute("id", {})

    asyncio.run(run())

    events = _read_events(journal)
    assert [e["event_type"] for e in events] == ["tool.called", "budget", "tool.finished"]
    assert events[1]["payload"]["kind"] == "search"
    assert events[2]["payload"]["status"] == "error"


def test_eval_journal_stream_emits_request_response_with_usage(tmp_path):
    journal = RunJournal("run-4", tmp_path / "runs" / "run-4" / "events.jsonl")
    model = {"id": "deepseek-v3.2", "provider": "openai"}

    async def fake_stream(model, context, options=None):
        yield {"type": "text_start", "text": ""}
        yield {
            "type": "done",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "hi"}],
                "usage": {
                    "input": 10,
                    "output": 5,
                    "cacheRead": 0,
                    "cacheWrite": 0,
                    "cost": {"total": 0.0},
                },
            },
        }

    async def run():
        stream = EvalJournalStream(fake_stream, journal)
        events = []
        async for event in stream(model, {"messages": []}):
            events.append(event)

    asyncio.run(run())

    events = _read_events(journal)
    assert [e["event_type"] for e in events] == ["llm.request", "llm.response"]
    assert events[0]["payload"]["model"] == "deepseek-v3.2"
    assert events[1]["payload"]["status"] == "ok"
    assert events[1]["payload"]["usage"]["input"] == 10


def test_sanitize_options_strips_harness_injected_fields():
    """harness 注入的 signal/sessionId/transport 会压制 toolcall → 转发前剥离。"""
    opts = {"signal": object(), "sessionId": "x", "transport": "rest", "temperature": 0.2}
    cleaned = _sanitize_options(opts)
    assert cleaned == {"temperature": 0.2}
    assert _sanitize_options(None) is None


def test_sanitize_context_strips_message_timestamp():
    ctx = {
        "systemPrompt": "sp",
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "hi"}], "timestamp": 123},
            {"role": "assistant", "content": [], "timestamp": 456},
        ],
    }
    cleaned = _sanitize_context(ctx)
    assert "timestamp" not in cleaned["messages"][0]
    assert "timestamp" not in cleaned["messages"][1]
    assert cleaned["messages"][0]["content"] == [{"type": "text", "text": "hi"}]
    # 无 timestamp 时不复制
    assert _sanitize_context({"messages": [{"role": "user", "content": []}]})["messages"][0] == {
        "role": "user",
        "content": [],
    }


def test_eval_journal_stream_emits_error_status_on_error_terminal(tmp_path):
    journal = RunJournal("run-5", tmp_path / "runs" / "run-5" / "events.jsonl")
    model = {"id": "deepseek-v3.2", "provider": "openai"}

    async def fake_stream(model, context, options=None):
        yield {
            "type": "error",
            "error": {"role": "assistant", "content": [], "error": {"type": "timeout"}},
        }

    async def run():
        stream = EvalJournalStream(fake_stream, journal)
        async for _ in stream(model, {"messages": []}):
            pass

    asyncio.run(run())

    events = _read_events(journal)
    assert events[1]["payload"]["status"] == "error"
    assert events[1]["payload"]["errorType"] == "timeout"
