"""FallbackStream tests — poirot test_model_router.py 断言语义平移 + ragent 探测语义。

Transplant source: HezaoHezao/poirot
Path: poirot/backend/tests/v1/unit/config/test_model_router.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see native/vendor/licenses/POIROT-MIT.txt)
ADAPT (plan §3 阶段 3): ``FakeListChatModel``（LangChain 替身）→ pi scripted
事件流替身; 判定断言从异常改 ``error`` 字段 (ADR 0015)。
"""

from __future__ import annotations

import asyncio

from competitive_app.application.model.fallback_stream import (
    DEFAULT_FIRST_PACKET_TIMEOUT_MS,
    FallbackStream,
    _should_fallback,
)
from earendil_works.pi_ai.api._http_stream import error_message
from earendil_works.pi_ai.types import (
    AssistantMessage,
    AssistantMessageEvent,
    Context,
    Model,
    empty_usage,
)
from earendil_works.pi_ai.utils.event_stream import AssistantMessageEventStream


def _chain_model(provider: str) -> Model:
    return {
        "id": f"m-{provider}",
        "name": f"m-{provider}",
        "api": "openai-completions",
        "provider": provider,
        "baseUrl": "http://localhost:0",
        "reasoning": False,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 8,
        "maxTokens": 8,
    }


MODEL_A = _chain_model("alpha")
MODEL_B = _chain_model("beta")
CTX: Context = {"messages": [{"role": "user", "content": "hi", "timestamp": 0}]}


def _error_event(
    model: Model,
    status: int | None = None,
    error_type: str | None = None,
) -> AssistantMessageEvent:
    message = _error_message(model, status=status, error_type=error_type)
    return {"type": "error", "reason": "error", "error": message}


def _done_event(model: Model, text: str = "ok") -> AssistantMessageEvent:
    return {"type": "done", "reason": "stop", "message": _ok_message(model, text)}


def _error_message(model: Model, status: int | None = None, error_type: str | None = None) -> AssistantMessage:
    if error_type is not None:
        # 直接构造（分类测试用）；HTTP 路径走 error_message 产点
        info: dict = {"type": error_type, "message": "x"}
        if status is not None:
            info["statusCode"] = status
        return {
            "role": "assistant", "content": [], "api": "a", "provider": model["provider"],
            "model": model["id"], "usage": empty_usage(), "stopReason": "error",
            "errorMessage": "x", "error": info,
        }
    if status is not None:
        return error_message(model, f"HTTP {status}: boom", status_code=status)
    return error_message(model, "boom")


def _ok_message(model: Model, text: str = "ok") -> AssistantMessage:
    return {
        "role": "assistant", "content": [{"type": "text", "text": text}],
        "api": "a", "provider": model["provider"], "model": model["id"],
        "usage": empty_usage(), "stopReason": "stop", "timestamp": 0,
    }


def _events(*events: AssistantMessageEvent) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()
    for event in events:
        stream.push(event)
    return stream


def _delayed_events(events: list[AssistantMessageEvent], delay: float) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()

    async def runner() -> None:
        await asyncio.sleep(delay)
        for event in events:
            stream.push(event)

    asyncio.create_task(runner())
    return stream




class _FakeModels:
    """pi scripted 事件流替身（FakeListChatModel → pi streamSimple）。"""

    def __init__(self, plan: dict[str, list[AssistantMessageEvent] | object], delays: dict[str, float] | None = None) -> None:
        self.plan = plan
        self.delays = delays or {}
        self.calls: list[Model] = []
        self.signals: list[object] = []
    def streamSimple(self, model: Model, context: Context, options: object | None = None) -> AssistantMessageEventStream:
        self.calls.append(model)
        self.signals.append((options or {}).get("signal") if isinstance(options, dict) else None)
        entry = self.plan.get(model["provider"])
        delay = self.delays.get(model["provider"], 0.0)
        if callable(entry):
            return entry()
        if delay:
            return _delayed_events(list(entry), delay)
        return _events(*entry)


async def _collect(fallback: FallbackStream, model: Model, context: Context = CTX) -> tuple[list[AssistantMessageEvent], AssistantMessage]:
    stream = fallback(model, context, None)
    events = [event async for event in stream]
    message = await stream.result()
    return events, message


# --- _should_fallback（poirot 分类表：异常面 → error 字段）---

def test_should_fallback_on_timeout() -> None:
    assert _should_fallback({"type": "timeout", "message": "x"}) is True


def test_should_fallback_on_connection() -> None:
    assert _should_fallback({"type": "connection", "message": "x"}) is True


def test_should_fallback_on_429_and_5xx() -> None:
    assert _should_fallback({"type": "http_error", "statusCode": 429, "message": "x"}) is True
    assert _should_fallback({"type": "http_error", "statusCode": 500, "message": "x"}) is True
    assert _should_fallback({"type": "http_error", "statusCode": 503, "message": "x"}) is True


def test_should_not_fallback_on_client_error() -> None:
    for status in (400, 401, 403, 404):
        assert _should_fallback({"type": "http_error", "statusCode": status, "message": "x"}) is False


def test_should_not_fallback_on_unknown_or_missing() -> None:
    assert _should_fallback(None) is False
    assert _should_fallback({"type": "other", "message": "x"}) is False
    assert _should_fallback({"type": "aborted", "message": "x"}) is False


# --- FallbackStream 轮转（poirot _agenerate 语义）---

async def test_fallback_on_transient_error() -> None:
    """首 provider 429 → 第二成功；_active 记忆降级后的 provider。"""
    models = _FakeModels(
        {
            "alpha": [_error_event(MODEL_A, status=429)],
            "beta": [_done_event(MODEL_B)],
        }
    )
    fallback = FallbackStream(models, chain=[MODEL_A, MODEL_B])
    events, message = await _collect(fallback, MODEL_A)
    assert [m["provider"] for m in models.calls] == ["alpha", "beta"]
    assert message["provider"] == "beta"
    assert events[-1]["type"] == "done"
    assert fallback._active == 1  # 记忆降级后的 provider


async def test_active_memory_starts_from_last_success() -> None:
    """下次调用从上次成功 provider 起试，无再降级。"""
    models = _FakeModels(
        {
            "alpha": [_error_event(MODEL_A, status=429)],
            "beta": [_done_event(MODEL_B)],
        }
    )
    fallback = FallbackStream(models, chain=[MODEL_A, MODEL_B])
    await _collect(fallback, MODEL_A)
    assert fallback._active == 1
    await _collect(fallback, MODEL_A)
    assert [m["provider"] for m in models.calls] == ["alpha", "beta", "beta"]


async def test_client_error_propagates_without_fallback() -> None:
    """客户端错误（400/401/404）不降级，原样透出。"""
    models = _FakeModels({"alpha": [_error_event(MODEL_A, status=401)]})
    fallback = FallbackStream(models, chain=[MODEL_A, MODEL_B])
    events, message = await _collect(fallback, MODEL_A)
    assert len(models.calls) == 1
    assert message["stopReason"] == "error"
    assert message["error"]["type"] == "http_error"
    assert message["error"]["statusCode"] == 401
    assert events[-1]["type"] == "error"


async def test_all_failures_returns_last_error() -> None:
    """全链失败返回最后 error 消息（G8：不抛异常）。"""
    models = _FakeModels(
        {
            "alpha": [_error_event(MODEL_A, status=429)],
            "beta": [_error_event(MODEL_B, status=500)],
        }
    )
    fallback = FallbackStream(models, chain=[MODEL_A, MODEL_B])
    events, message = await _collect(fallback, MODEL_A)
    assert [m["provider"] for m in models.calls] == ["alpha", "beta"]
    assert message["stopReason"] == "error"
    assert message["error"]["statusCode"] == 500
    assert events[-1]["type"] == "error"


async def test_single_chain_is_passthrough() -> None:
    """chain 为空/单元素 → 直通（B8/未设 env）：返回 models 原流，无探测无缓冲。"""
    models = _FakeModels({"alpha": [{"type": "done", "reason": "stop", "message": _ok_message(MODEL_A)}]})
    fallback = FallbackStream(models)  # chain=None
    stream = fallback(MODEL_A, CTX, None)
    # 直通：返回的就是 models 的流对象本身
    assert stream is not None
    events = [event async for event in stream]
    assert events[-1]["type"] == "done"


# --- 首包探测 + 全程缓冲（ragent 语义）---

async def test_first_packet_timeout_switches_provider() -> None:
    """首包超时（注入短 LLM_FALLBACK_FIRST_PACKET_MS）→ 取消当前流切下家。"""
    models = _FakeModels(
        {
            "alpha": [_done_event(MODEL_A)],
            "beta": [_done_event(MODEL_B)],
        },
        delays={"alpha": 0.2},
    )
    fallback = FallbackStream(models, chain=[MODEL_A, MODEL_B], first_packet_timeout_ms=50)
    _collected_events, message = await _collect(fallback, MODEL_A)
    assert [m["provider"] for m in models.calls] == ["alpha", "beta"]
    assert message["provider"] == "beta"
    # 当前流已通过 per-attempt signal 取消
    assert models.signals[0].is_set() is True


async def test_error_after_first_packet_switches_without_partial_delivery() -> None:
    """首包成功后中途 error → 切下家重放且下游无半截（G7a 缓冲语义）。"""
    start: AssistantMessageEvent = {"type": "start", "partial": _ok_message(MODEL_A)}
    text_start: AssistantMessageEvent = {
        "type": "text_start", "contentIndex": 0, "partial": _ok_message(MODEL_A, "partial-a")
    }
    mid_error: AssistantMessageEvent = {
        "type": "error", "reason": "error", "error": _error_message(MODEL_A, error_type="timeout")
    }
    done_b: AssistantMessageEvent = {"type": "done", "reason": "stop", "message": _ok_message(MODEL_B, "ok-b")}
    models = _FakeModels({"alpha": [start, text_start, mid_error], "beta": [done_b]})
    fallback = FallbackStream(models, chain=[MODEL_A, MODEL_B])
    events, message = await _collect(fallback, MODEL_A)
    assert [m["provider"] for m in models.calls] == ["alpha", "beta"]
    # 下游只见 beta 的完整缓冲（alpha 半截丢弃）
    assert events == [done_b]
    assert message["content"][0]["text"] == "ok-b"


async def test_success_delivers_full_buffer_batch() -> None:
    """done 才一次性交付缓冲（G7c 批式）。"""
    done: AssistantMessageEvent = {"type": "done", "reason": "stop", "message": _ok_message(MODEL_A, "final")}
    models = _FakeModels(
        {
            "alpha": [
                {"type": "start", "partial": _ok_message(MODEL_A)},
                {"type": "text_start", "contentIndex": 0, "partial": _ok_message(MODEL_A, "p")},
                {"type": "text_delta", "contentIndex": 0, "delta": "a", "partial": _ok_message(MODEL_A, "pa")},
                {"type": "text_end", "contentIndex": 0, "partial": _ok_message(MODEL_A, "pa")},
                done,
            ]
        }
    )
    fallback = FallbackStream(models, chain=[MODEL_A])
    # 单元素链直通——用双元素链验证缓冲路径
    fallback = FallbackStream(models, chain=[MODEL_A, MODEL_B])
    events, message = await _collect(fallback, MODEL_A)
    assert [e["type"] for e in events] == ["start", "text_start", "text_delta", "text_end", "done"]
    assert message["content"][0]["text"] == "final"


async def test_concurrent_instances_have_independent_active() -> None:
    """并发实例独立（无共享 _active）。"""
    models = _FakeModels(
        {
            "alpha": [_error_event(MODEL_A, status=429)],
            "beta": [_done_event(MODEL_B)],
        }
    )
    fallback1 = FallbackStream(models, chain=[MODEL_A, MODEL_B])
    fallback2 = FallbackStream(models, chain=[MODEL_A, MODEL_B])
    await _collect(fallback1, MODEL_A)
    assert fallback1._active == 1
    assert fallback2._active == 0
    await _collect(fallback2, MODEL_A)
    # 实例 2 第一轮从 alpha 起试（自己的 _active=0）
    assert models.calls[-1]["provider"] == "beta"


async def test_fallback_journal_events_emitted() -> None:
    """llm.fallback_start / switch / exhausted 事件序列。"""
    models = _FakeModels(
        {
            "alpha": [_error_event(MODEL_A, status=429)],
            "beta": [_error_event(MODEL_B, status=500)],
        }
    )
    journal: list[tuple[str, dict]] = []
    fallback = FallbackStream(
        models,
        chain=[MODEL_A, MODEL_B],
        emit_fallback_event=lambda t, p: journal.append((t, p)),
    )
    await _collect(fallback, MODEL_A)
    assert [t for t, _ in journal] == ["llm.fallback_start", "llm.fallback_switch", "llm.fallback_exhausted"]
    assert journal[1][1]["fromProvider"] == "alpha"
    assert journal[1][1]["toProvider"] == "beta"
    assert journal[2][1]["lastProvider"] == "beta"


async def test_fallback_journal_sink_failure_does_not_block() -> None:
    """journal sink 抛异常不阻断 LLM 调用。"""
    models = _FakeModels(
        {
            "alpha": [_error_event(MODEL_A, status=429)],
            "beta": [_done_event(MODEL_B)],
        }
    )

    def boom(_t, _p):
        raise RuntimeError("journal broken")

    fallback = FallbackStream(models, chain=[MODEL_A, MODEL_B], emit_fallback_event=boom)
    _, message = await _collect(fallback, MODEL_A)
    assert message["provider"] == "beta"


async def test_aborted_message_not_fallback() -> None:
    """aborted（用户取消）→ 原样透出，不切 provider。"""
    aborted_msg = _error_message(MODEL_A, error_type="aborted")
    aborted_msg["stopReason"] = "aborted"
    models = _FakeModels(
        {
            "alpha": [{"type": "error", "reason": "aborted", "error": aborted_msg}],
            "beta": [{"type": "done", "reason": "stop", "message": _ok_message(MODEL_B)}],
        }
    )
    fallback = FallbackStream(models, chain=[MODEL_A, MODEL_B])
    events, message = await _collect(fallback, MODEL_A)
    assert len(models.calls) == 1
    assert message["stopReason"] == "aborted"
    assert events[-1]["reason"] == "aborted"


async def test_default_first_packet_timeout_value() -> None:
    assert DEFAULT_FIRST_PACKET_TIMEOUT_MS == 60000
