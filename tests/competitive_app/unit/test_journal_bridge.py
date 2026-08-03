"""JournalBridge tests — 行为语义对齐 poirot RunJournalMiddleware + feature §3.3 表。

正常功能：extension 事件 → journal 事件序列映射正确。
鲁棒性：白名单拒绝未知（B10）；脱敏（密钥/凭据不落，B9）；tool 输出截 2000；
无 journal 时静默不报错。
"""

from __future__ import annotations

from typing import Any

from competitive_app.adapter.out.observability import (
    guarded_append,
    is_journal_event_allowed,
    redact_payload,
)
from competitive_app.application.workflow.journal_bridge import make_journal_extension_factory


class _RecordingJournal:
    """记录 appends 的 journal 替身（不落盘，断言用）。"""

    def __init__(self, run_id: str = "run-1") -> None:
        self.run_id = run_id
        self.events: list[tuple[str, dict[str, Any]]] = []

    def append(self, event_type: str, payload: dict[str, Any] | None = None) -> Any:
        self.events.append((event_type, payload or {}))
        return None


class _FakeAPI:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}

    def on(self, event: str, handler: Any) -> None:
        self.handlers[event] = handler


def _make_bridge(journal: Any) -> tuple[_FakeAPI, Any]:
    api = _FakeAPI()
    make_journal_extension_factory(journal)(api)
    return api, journal


async def _fire(api: _FakeAPI, event_type: str, event: dict[str, Any]) -> None:
    handler = api.handlers[event_type]
    await handler(event, None)


def _typed(event_type: str, **payload: Any) -> dict[str, Any]:
    return {"type": event_type, **payload}


# --- 正常功能：事件映射（feature §3.3 表）---

async def test_agent_lifecycle_mapping() -> None:
    api, journal = _make_bridge(_RecordingJournal())
    await _fire(api, "agent_start", _typed("agent_start"))
    await _fire(api, "agent_settled", _typed("agent_settled"))
    assert journal.events == [
        ("agent.started", {"run_id": "run-1"}),
        ("agent.finished", {"run_id": "run-1"}),
    ]


async def test_llm_request_response_mapping() -> None:
    api, journal = _make_bridge(_RecordingJournal())
    await _fire(
        api,
        "before_provider_request",
        _typed("before_provider_request", payload={"model": "glm-5.2", "stream": True}),
    )
    await _fire(
        api,
        "after_provider_response",
        _typed("after_provider_response", status=200, headers={"x-request-id": "r1"}),
    )
    assert journal.events == [
        ("llm.request", {"run_id": "run-1", "model": "glm-5.2"}),
        ("llm.response", {"run_id": "run-1", "model": "glm-5.2", "status": 200}),
    ]


async def test_tool_call_result_mapping() -> None:
    api, journal = _make_bridge(_RecordingJournal())
    await _fire(
        api,
        "tool_call",
        _typed("tool_call", toolCallId="t1", toolName="search", input={"q": "x"}),
    )
    await _fire(
        api,
        "tool_result",
        _typed(
            "tool_result",
            toolCallId="t1",
            toolName="search",
            content=[{"type": "text", "text": "found"}],
            isError=False,
        ),
    )
    assert journal.events == [
        ("tool.called", {"run_id": "run-1", "tool_name": "search", "tool_input": {"q": "x"}}),
        ("tool.finished", {"run_id": "run-1", "tool_name": "search", "output": "found", "status": "ok"}),
    ]


async def test_compaction_mapping() -> None:
    api, journal = _make_bridge(_RecordingJournal())
    await _fire(
        api,
        "session_before_compact",
        _typed("session_before_compact", reason="manual", willRetry=False),
    )
    await _fire(
        api,
        "session_compact",
        _typed("session_compact", reason="manual", fromExtension=False),
    )
    assert journal.events == [
        ("compaction.requested", {"run_id": "run-1", "reason": "manual", "willRetry": False}),
        ("compaction.completed", {"run_id": "run-1", "reason": "manual", "fromExtension": False}),
    ]


# --- 鲁棒性：白名单 / 脱敏 / 截断 / 静默 ---

def test_whitelist_rejects_unknown_type() -> None:
    journal = _RecordingJournal()
    assert guarded_append(journal, "unknown.event", {}) is False
    assert journal.events == []


def test_whitelist_allows_prefix_types() -> None:
    journal = _RecordingJournal()
    assert guarded_append(journal, "task.created", {"id": "t1"}) is True
    assert guarded_append(journal, "compaction.requested", {}) is True
    assert is_journal_event_allowed("task.progress") is True
    assert is_journal_event_allowed("llm.fallback_switch") is True


def test_redaction_blacklist() -> None:
    payload = {
        "query": "keep me",
        "api_key": "sk-123",
        "Authorization": "Bearer tok",
        "nested": {"password": "p", "keep": 1},
        "items": [{"credential": "c", "ok": True}],
        "max_tokens": 100,  # 合法参数（后缀是 tokens 非 _token），不脱敏
        "access_token": "at-9",  # _token 后缀 → 脱敏
    }
    redacted = redact_payload(payload)
    assert redacted["query"] == "keep me"
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["nested"]["password"] == "[REDACTED]"
    assert redacted["nested"]["keep"] == 1
    assert redacted["max_tokens"] == 100
    assert redacted["access_token"] == "[REDACTED]"
    # 原 payload 不被修改（深拷贝）
    assert payload["api_key"] == "sk-123"


def test_tool_output_truncated_to_2000() -> None:
    api, journal = _make_bridge(_RecordingJournal())
    long_text = "x" * 5000
    handler = api.handlers["tool_result"]

    async def run() -> None:
        await handler(
            _typed("tool_result", toolCallId="t1", toolName="fetch", content=[{"type": "text", "text": long_text}], isError=False),
            None,
        )

    import asyncio

    asyncio.run(run())
    assert len(journal.events) == 1
    assert journal.events[0][0] == "tool.finished"
    assert len(journal.events[0][1]["output"]) == 2000


def test_no_journal_silent_noop() -> None:
    api = _FakeAPI()
    register = make_journal_extension_factory(None)
    register(api)  # 不抛
    assert api.handlers == {}
