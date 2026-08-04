"""Faux integration — multi-LLM fallback + RunJournal end-to-end (plan §3.1 faux 层).

Covers:
- 一次完整 research run → `events.jsonl` 完整序列（agent.started → llm.* ×N →
  tool.* → task.*/trace.span → agent.finished），_make_emit 三写就位；
- task 删除级联删 run 目录；
- FallbackStream（链轮转 + _active 记忆 + 全链失败）经 journal sink
  落 `llm.fallback_start/switch/exhausted`（offline，无真实网络）。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from competitive_app.adapter.out.observability import guarded_append
from competitive_app.adapter.out.observability.run_journal import RunJournal
from competitive_app.application.model.fallback_stream import FallbackStream
from earendil_works.pi_ai.api._http_stream import error_message
from earendil_works.pi_ai.providers.faux import faux_assistant_message, faux_tool_call
from earendil_works.pi_ai.types import (
    Context,
    Model,
)
from earendil_works.pi_ai.utils.event_stream import AssistantMessageEventStream
from httpx import ASGITransport, AsyncClient


def _plan_response(target: str = "ACME", competitor: str = "Beta") -> str:
    return json.dumps(
        {
            "plan": f"Search {target} and {competitor} pricing pages.",
            "coverage_schema": {
                "table_id": "t_competitive",
                "entities": [
                    {"id": "e_acme", "name": target, "kind": "target"},
                    {"id": "e_beta", "name": competitor, "kind": "competitor"},
                ],
                "attributes": [
                    {"id": "a_price", "name": "Price", "dimension": "pricing", "type": "money_usd"}
                ],
            },
        }
    )


def _judge_response(value: str = "$10/mo") -> str:
    return json.dumps(
        [
            {
                "attribute": "a_price",
                "value": value,
                "source": "https://example.com/pricing",
                "source_excerpt": f"costs {value} per month",
                "confidence": 0.9,
            }
        ]
    )


def _write_response() -> str:
    return '{"report": "ACME vs Beta pricing comparison [1].\\n\\n## Sources\\n[1] https://example.com/"}'


def _entity_responses(slug: str, price: str) -> list:
    return [
        faux_assistant_message([faux_tool_call("test_fetch", {"url": f"https://example.com/{slug}"})]),
        faux_assistant_message("done searching"),
        faux_assistant_message(_judge_response(price)),
    ]


def _full_three_stage_responses() -> list:
    return [
        faux_assistant_message(_plan_response()),
        *_entity_responses("acme", "$10/mo"),
        *_entity_responses("beta", "$20/mo"),
        faux_assistant_message(_write_response()),
    ]


_TASK_BODY = {
    "research_brief": {
        "target": {"name": "ACME", "category": "SaaS"},
        "goal": "analyze ACME vs Beta pricing",
        "competitors": ["ACME", "Beta"],
        "dimensions": ["pricing"],
    },
    "metadata": {"trace": "t1"},
}


async def _wait_status(client: AsyncClient, task_id: str, terminal: set[str], timeout: float = 30.0):
    deadline = asyncio.get_event_loop().time() + timeout
    status = "pending"
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/api/v2/tasks/{task_id}")
        status = resp.json().get("status")
        if status in terminal:
            return status
        await asyncio.sleep(0.05)
    return status


@pytest.fixture
async def runs_app_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """app_state 同款，但 RUNS_ROOT 指向 tmp（run 目录断言/删除断言隔离）。"""
    monkeypatch.setenv("USE_FAUX", "1")
    monkeypatch.setenv("SESSIONS_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("APP_DB", str(tmp_path / "app.db"))
    monkeypatch.setenv("SESSIONS_CWD", "test")
    monkeypatch.setenv("CAPABILITY_PACKAGES_ENABLED", "echo_example,reasonix_prefix_cache")
    monkeypatch.setenv("PROMPT_LOCK_TIMEOUT", "2")
    monkeypatch.setenv("SEARCH_MAX_PARALLEL", "1")
    monkeypatch.setenv("RUNS_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("LLM_FALLBACK_PROVIDERS", "")
    monkeypatch.setenv("LLM_FALLBACK_DISABLED", "1")

    from competitive_app.adapter.in_.fastapi.app import create_app
    from competitive_app.wiring import build_application_state, load_config_from_env

    from tests.competitive_app.conftest import _TestSandboxLifecycle, _TestToolExecutor

    config = load_config_from_env()
    state = await build_application_state(
        config,
        tool_executor=_TestToolExecutor(),
        sandbox_lifecycle=_TestSandboxLifecycle(),
    )
    app = create_app()
    app.state.application = state  # type: ignore[attr-defined]
    state._app = app  # expose for the integration client
    try:
        yield state
    finally:
        await state.shutdown()


def _read_events(path: Path) -> list[dict[str, Any]]:
    # events.jsonl is strict line-delimited JSON: one object per line.
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]



@pytest.fixture
def runs_faux(runs_app_state):
    """The faux handle bound to runs_app_state's own models (NOT conftest's)."""
    return getattr(runs_app_state.models, "_ApplicationState__faux", None) or getattr(
        runs_app_state.models, "__faux", None
    )


@pytest.fixture
def runs_mock_fetch_tool(runs_app_state):
    """test_fetch mock bound to runs_app_state's task_service (conftest's mock
    targets the other app_state)."""
    from earendil_works.pi_agent.types import AgentTool

    PRICES = {"acme": "$10/mo", "beta": "$20/mo"}

    async def _execute(tool_call_id: str, params: Any, signal=None, on_update=None):
        url = params.get("url", "") if isinstance(params, dict) else ""
        price = "$0"
        for slug, p in PRICES.items():
            if slug in url.lower():
                price = p
                break
        page_text = f"Pricing page for {url}. The plan costs {price} per month."
        return {
            "content": [{"type": "text", "text": page_text}],
            "details": {"url": url, "content": page_text},
        }

    tool = AgentTool(
        name="test_fetch",
        description="Offline mock fetch for tests (returns a page with pricing).",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        label="Test Fetch",
        execute=_execute,
        executionMode="parallel",
    )
    runs_app_state.task_service._capability_tools.append(tool)
    yield tool
    runs_app_state.task_service._capability_tools.remove(tool)


@pytest.mark.asyncio
async def test_journal_full_sequence_and_delete_cascade(
    runs_app_state, runs_faux, runs_mock_fetch_tool
):
    """一次完整 research run：events.jsonl 全序列 + task 删除级联删 run 目录。"""
    runs_faux["setResponses"](_full_three_stage_responses())
    runs_root = Path(runs_app_state.config.runs_root)
    async with AsyncClient(
        transport=ASGITransport(app=runs_app_state._app), base_url="http://test"
    ) as client:
        create = await client.post("/api/v2/tasks", json=_TASK_BODY)
        assert create.status_code == 202, create.text
        task_id = create.json()["task_id"]
        status = await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        assert status == "completed", f"expected completed, got {status}"

        events_path = runs_root / task_id / "events.jsonl"
        assert events_path.is_file(), f"missing journal: {events_path}"
        events = _read_events(events_path)
        types = [e["event_type"] for e in events]

        # 序列锚点：run 事件开篇（stage_start 先于 agent 生命周期），
        # agent 生命周期包住全部 LLM/工具事件。
        assert types[0] == "task.stage_start", types
        assert "agent.started" in types
        assert "agent.finished" in types
        assert types.index("agent.started") < types.index("llm.request")
        assert types.index("llm.request") < types.index("llm.response")
        assert types.index("llm.response") < types.index("agent.finished")
        # llm.request/response 成对出现（≥1 轮）。
        assert types.count("llm.request") >= 1
        assert types.count("llm.response") >= 1
        # 工具调用（sub-agent fetch）。
        assert "tool.called" in types
        assert "tool.finished" in types
        assert types.index("tool.called") < types.index("tool.finished")
        # 三写：trace.span + task.* 业务事件。
        assert "trace.span" in types
        assert any(t.startswith("task.") for t in types)
        assert "task.stage_end" in types
        # 直连 append 点（write 阶段末尾，agent.finished 之后）。
        assert "report.generated" in types
        assert types.index("agent.finished") < types.index("report.generated")
        # 每个事件 payload 脱敏就绪且 run_id 正确。
        for event in events:
            assert event["run_id"] == task_id

        # 删除级联：run 目录 + journal 缓存清理。
        await client.delete(f"/api/v2/tasks/{task_id}")
        assert not (runs_root / task_id).exists()


@pytest.mark.asyncio
async def test_fallback_stream_journal_events_offline(tmp_path: Path, runs_app_state, runs_faux):
    """FallbackStream 链轮转 + _active 记忆 + 全链失败 → journal fallback 事件。

    offline：坏 provider 的 streamSimple 返回 scripted connection-error 流；
    好 provider = faux 真流。断言 journal 事件（llm.fallback_start/switch/
    exhausted）与第二次调用 _active 记忆（无 switch）。
    """
    runs_faux["setResponses"]([faux_assistant_message("recovered via fallback")])
    faux_model = runs_faux["getModel"]()
    models = runs_app_state.models

    journal = RunJournal("run-fallback", tmp_path / "runs" / "events.jsonl")

    def sink(event_type: str, payload: dict[str, Any]) -> None:
        guarded_append(journal, event_type, payload)

    def bad_model(provider: str, model_id: str) -> Model:
        return {
            "id": model_id, "name": model_id, "api": "openai-completions",
            "provider": provider, "baseUrl": "http://127.0.0.1:9",
            "reasoning": False, "input": ["text"],
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            "contextWindow": 128000, "maxTokens": 8192,
        }

    def _error_stream(model: Model) -> AssistantMessageEventStream:
        message = error_message(model, "connection refused", status_code=None)
        message["error"] = {"type": "connection", "message": "connection refused"}
        stream = AssistantMessageEventStream()
        stream.push({"type": "error", "reason": "error", "error": message})
        stream.end(message)
        return stream

    real_stream = models.streamSimple

    def failing_stream(model: Model, context: Context, options: Any = None) -> Any:
        if model["provider"] == "broken":
            return _error_stream(model)
        return real_stream(model, context, options)

    broken = bad_model("broken", "m-broken")
    good = faux_model
    fs = FallbackStream(
        _FakeDelegate(models, failing_stream),
        chain=[broken, good],
        first_packet_timeout_ms=1000,
        emit_fallback_event=sink,
    )
    ctx: Context = {"messages": [{"role": "user", "content": "hi", "timestamp": 0}]}

    # 第一次调用：broken 首包 connection error → switch → faux 成功。
    stream = fs(good, ctx, None)
    events = [e async for e in stream]
    result = await stream.result()
    assert result["stopReason"] == "stop"
    assert any(e["type"] == "done" for e in events)
    journal_events = _read_events(tmp_path / "runs" / "events.jsonl")
    fallback_types = [e["event_type"] for e in journal_events]
    assert "llm.fallback_start" in fallback_types
    assert "llm.fallback_switch" in fallback_types
    switch = next(e for e in journal_events if e["event_type"] == "llm.fallback_switch")
    assert switch["payload"]["fromProvider"] == "broken"
    assert switch["payload"]["toProvider"] == faux_model["provider"]
    assert switch["payload"]["reason"] == "connection"

    # 第二次调用（同一 FallbackStream 实例）：_active 记忆 → 直接从 faux 起，
    # journal 只多一个 fallback_start、无第二个 fallback_switch。
    stream2 = fs(good, ctx, None)
    await stream2.result()
    events_after = _read_events(tmp_path / "runs" / "events.jsonl")
    types_after = [e["event_type"] for e in events_after]
    assert types_after.count("llm.fallback_start") == 2
    assert types_after.count("llm.fallback_switch") == 1
    journal3 = RunJournal("run-fallback-3", tmp_path / "runs" / "events3.jsonl")
    fs3 = FallbackStream(
        _FakeDelegate(models, failing_stream),
        chain=[broken, broken],
        first_packet_timeout_ms=1000,
        emit_fallback_event=lambda t, p: guarded_append(journal3, t, p),
    )
    stream3 = fs3(good, ctx, None)
    stream_events = [e async for e in stream3]
    failed = await stream3.result()
    assert failed["stopReason"] == "error"
    assert failed["error"]["type"] == "connection"
    assert stream_events[-1]["type"] == "error"
    types3 = [e["event_type"] for e in _read_events(journal3.events_path)]
    assert "llm.fallback_exhausted" in types3


class _FakeDelegate:
    """Real models wrapper — delegates streamSimple to a test seam (bad providers
    → scripted error streams; everything else → real faux stream)."""

    def __init__(self, real: Any, stream_fn: Any) -> None:
        self._real = real
        self._stream_fn = stream_fn

    def streamSimple(self, model: Model, context: Context, options: Any = None) -> Any:
        return self._stream_fn(model, context, options)
