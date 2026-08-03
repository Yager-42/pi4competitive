"""Live tests — multi-LLM fallback switch + journal llm events (plan §3.2).

只证链路跑通（真实 provider 调用 → 失败识别 → 切换 → journal 事件落盘）；
降级后的"结果正确性"归 offline 断言（live 测试纪律）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from competitive_app.adapter.out.observability import guarded_append
from competitive_app.adapter.out.observability.run_journal import RunJournal
from competitive_app.application.model.fallback_stream import FallbackStream
from competitive_app.application.model.journal_stream import JournalStream
from earendil_works.pi_ai import create_models
from earendil_works.pi_ai.providers.openai import openai_provider
from earendil_works.pi_ai.types import Context

from tests.live_env import live_openai_model


def _dead_model(creds: dict[str, str]) -> dict:
    """Same provider/api as the real model, but a dead endpoint (connect refused)."""
    model = live_openai_model(creds)
    return {**model, "baseUrl": "http://127.0.0.1:9/v1", "id": "dead-endpoint-model"}


def _read_events(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    return [__import__("json").loads(block) for block in raw.split("\n\n") if block.strip()]


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_fallback_switch(live_env, tmp_path: Path):
    """链 = [死 endpoint（首包必败 connection）, 真 key provider] → 自动切换 → 真实
    LLM 成功；journal 含 llm.fallback_start/llm.fallback_switch；_active 记忆生效
    （第二次调用无第二个 switch）。"""
    creds = live_env
    models = create_models()
    models.setProvider(openai_provider())

    journal = RunJournal("run-live-fallback", tmp_path / "events.jsonl")

    def sink(event_type: str, payload: dict[str, Any]) -> None:
        guarded_append(journal, event_type, payload)

    chain = [_dead_model(creds), live_openai_model(creds)]
    stream_fn = FallbackStream(
        models,
        chain=chain,
        first_packet_timeout_ms=30000,
        emit_fallback_event=sink,
    )
    ctx: Context = {"messages": [{"role": "user", "content": "reply with exactly: ok", "timestamp": 0}]}

    # 第一次调用：死 endpoint → connection error → switch → 真实 provider 成功。
    stream = stream_fn(chain[1], ctx, None)
    events = [e async for e in stream]
    result = await stream.result()
    assert result["stopReason"] == "stop", result.get("errorMessage") or result.get("error")
    assert any(e["type"] == "done" for e in events)

    events1 = _read_events(journal.events_path)
    types1 = [e["event_type"] for e in events1]
    assert "llm.fallback_start" in types1
    assert "llm.fallback_switch" in types1
    switch = next(e for e in events1 if e["event_type"] == "llm.fallback_switch")
    assert switch["payload"]["fromProvider"] == "openai"
    assert switch["payload"]["toProvider"] == "openai"
    # 直连环境 → connection；系统代理环境 → 代理 502（仍属可降级 5xx）。
    reason = switch["payload"]["reason"]
    assert reason == "connection" or reason.startswith("http_error:5"), reason

    # 第二次调用（同一实例）：_active 记忆 → 直接从好 provider 起，无第二个 switch。
    stream2 = stream_fn(chain[1], ctx, None)
    await stream2.result()
    types2 = [e["event_type"] for e in _read_events(journal.events_path)]
    assert types2.count("llm.fallback_start") == 2
    assert types2.count("llm.fallback_switch") == 1


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_journal_llm_events(live_env, tmp_path: Path):
    """真实 LLM 调用一轮（JournalStream 经 harness）→ events.jsonl 含
    llm.request/llm.response，payload.model = 实际 model id，request 先于 response。"""
    creds = live_env
    models = create_models()
    models.setProvider(openai_provider())

    journal = RunJournal("run-live-llm", tmp_path / "events.jsonl")

    def sink(event_type: str, payload: dict[str, Any]) -> None:
        guarded_append(journal, event_type, payload)

    stream_fn = JournalStream(models.streamSimple, sink)
    from earendil_works.pi_agent import AgentHarness, JsonlSessionRepo
    from earendil_works.pi_agent.harness.env.python_env import LocalFileSystem

    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)
    repo = JsonlSessionRepo({"fs": LocalFileSystem(cwd="test"), "sessionsRoot": str(sessions_root)})
    session = await repo.create({"cwd": "test"})
    model = live_openai_model(creds)
    harness = AgentHarness(session=session, stream_fn=stream_fn, model=model, system_prompt="")
    try:
        await harness.prompt("reply with exactly: ok")
    finally:
        await harness.shutdown()

    events = _read_events(journal.events_path)
    types = [e["event_type"] for e in events]
    assert "llm.request" in types
    assert "llm.response" in types
    assert types.index("llm.request") < types.index("llm.response")
    request = next(e for e in events if e["event_type"] == "llm.request")
    assert request["payload"]["model"] == model["id"], request["payload"]
    response = next(e for e in events if e["event_type"] == "llm.response")
    assert response["payload"]["status"] == "ok", response["payload"]
