"""FallbackStream — pi ``stream_fn`` wrapper: rotation chain + first-packet probe + full buffering.

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/config/fallback_model.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see native/vendor/licenses/POIROT-MIT.txt)
First-packet probe: Yager-42/ragent ``FirstPacketAwaiter`` / ``ProbeBufferingCallback``
(思想平移, Java → asyncio; no code copied).

COPY: ``FallbackChatModel._agenerate`` 骨架逐行 — ``for offset in range(n):
idx = (self._active + offset) % n`` 轮转、``self._active = idx`` 成功记忆、
全链失败控制流与注释语义。

ADAPT (plan P4-llm-fallback-observability §2 阶段 3, listed points only):
  1. ``self.models[idx].invoke(...)`` → pi 事件流消费：首包探测
     (``asyncio.wait_for`` + per-attempt signal 取消) + 全程缓冲批式交付
     (done 才一次性 push; 失败丢弃缓冲, G7a/G7c)。
     (ADR 0015), 分类表照抄 (timeout/connection/429/5xx → 降级;
     400/401/403/404 → 不降级)。
  3. ``bind_tools`` 删除 (pi streamSimple 自带 tools)。
  4. 全链失败 ``raise last_exc`` → 返回最后 error 消息 (G8, pi 语义不抛异常)。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from earendil_works.pi_ai.types import (
    AssistantMessage,
    AssistantMessageEvent,
    Context,
    ErrorInfo,
    Model,
    SimpleStreamOptions,
)
from earendil_works.pi_ai.utils.event_stream import AssistantMessageEventStream

DEFAULT_FIRST_PACKET_TIMEOUT_MS = 60000  # ragent FIRST_PACKET_TIMEOUT_SECONDS = 60

# B2 降级分类：type ∈ {timeout, connection} 或 http_error ∈ {429} ∪ [500,600)
_FALLBACK_TYPES = frozenset({"timeout", "connection"})
_CLIENT_ERROR_STATUS = frozenset({400, 401, 403, 404})

_FIRST_PACKET_EVENTS = frozenset({"text_start", "toolcall_start", "done"})
_TERMINAL_EVENTS = frozenset({"done", "error"})

FallbackEventSink = Callable[[str, dict[str, Any]], None]


def _should_fallback(error: ErrorInfo | None) -> bool:
    """是否应降级到下一个 provider。

    COPY poirot ``_should_fallback`` 语义（异常面 → ADR 0015 ``error`` 字段）：
    降级：超时/断连/限流/5xx 服务端错误（瞬时，换 provider 可能恢复）。
    不降级：400/401/403/404 等客户端错误（换 provider 也会失败，应原样透出）。
    """
    if not error:
        return False
    if error.get("type") in _FALLBACK_TYPES:
        return True
    if error.get("type") == "http_error":
        status = error.get("statusCode")
        if status is None:
            return False
        return status == 429 or 500 <= status < 600
    return False


class _AttemptSignal:
    """Per-attempt abort: own flag OR parent (harness) abort — 不影响共享 parent。"""

    def __init__(self, parent: Any = None) -> None:
        self._own = False
        self._parent = parent

    def set(self) -> None:
        self._own = True

    def is_set(self) -> bool:
        if self._own:
            return True
        if self._parent is None:
            return False
        if hasattr(self._parent, "is_set"):
            return bool(self._parent.is_set())
        return bool(getattr(self._parent, "aborted", False))

    @property
    def aborted(self) -> bool:
        return self.is_set()


class _Outcome:
    __slots__ = ("buffer", "kind", "message")
    # kind: "ok" (done) | "error" (terminal error event) | "timeout" (first-packet timeout)

    def __init__(
        self,
        kind: str,
        buffer: list[AssistantMessageEvent],
        message: AssistantMessage | None,
    ) -> None:
        self.kind = kind
        self.buffer = buffer
        self.message = message


class FallbackStream:
    """按链顺序调用，瞬时 API 失败降级到下一个，记忆活跃 provider。

    ``__call__`` 满足 pi ``StreamFn``（``ModelsImpl.streamSimple`` 兼容）：
    chain 为空/单元素 → 直通（B8 / env 未设）；否则返回缓冲批式交付的流。
    """

    def __init__(
        self,
        models: Any,
        chain: list[Model] | None = None,
        *,
        first_packet_timeout_ms: int | None = None,
        emit_fallback_event: FallbackEventSink | None = None,
    ) -> None:
        self._models = models
        self.chain: list[Model] = list(chain or [])
        self._active = 0
        self._first_packet_timeout = (
            first_packet_timeout_ms
            if first_packet_timeout_ms is not None
            else DEFAULT_FIRST_PACKET_TIMEOUT_MS
        ) / 1000.0
        self._emit_fallback_event = emit_fallback_event or (lambda _t, _p: None)

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        try:
            self._emit_fallback_event(event_type, payload)
        except Exception:
            logging.getLogger(__name__).warning(
                "fallback journal event failed", exc_info=True
            )

    def __call__(
        self,
        model: Model,
        context: Context,
        options: SimpleStreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        if len(self.chain) <= 1:
            # 直通（未设 LLM_FALLBACK_PROVIDERS / 单元素 / LLM_FALLBACK_DISABLED=1）：
            # 无探测无缓冲，纯透传。
            return self._models.streamSimple(model, context, options)
        return _FallbackCall(self, model, context, options)


class _FallbackCall(AssistantMessageEventStream):
    """单次调用的降级流：缓冲全部事件，done 后一次性交付。

    与 ``lazy_stream`` 同款 setup 模式：有运行 loop 直接建 task，否则推迟到首次迭代。
    """

    def __init__(
        self,
        owner: FallbackStream,
        model: Model,
        context: Context,
        options: SimpleStreamOptions | None,
    ) -> None:
        super().__init__()
        self._owner = owner
        self._model = model
        self._context = context
        self._options = options

        try:
            asyncio.get_running_loop().create_task(self._run())
        except RuntimeError:
            self._pending_run = self._run  # type: ignore[attr-defined]

            original = self._iterate

            async def _iterate_with_setup() -> AsyncIterator[AssistantMessageEvent]:
                if getattr(self, "_setup_started", False) is False:
                    self._setup_started = True  # type: ignore[attr-defined]
                    asyncio.create_task(self._run())
                async for item in original():
                    yield item

            self._iterate = _iterate_with_setup  # type: ignore[method-assign]

    async def _maybe_await(self, value: Any) -> Any:
        if isinstance(value, Awaitable):
            return await value
        return value

    async def _run(self) -> None:
        owner = self._owner
        # 链 = 配置原样（feature §3.2：streamSimple 按 dict 的 provider 字段路由）；
        # 调用方 model 只决定直通分支（chain ≤ 1），不参与链修正。
        chain = list(owner.chain)
        n = len(chain)
        last_error: AssistantMessage | None = None
        try:
            for offset in range(n):
                idx = (owner._active + offset) % n
                chain_model = chain[idx]
                if offset == 0:
                    owner._emit(
                        "llm.fallback_start",
                        {"provider": chain_model.get("provider"), "model": chain_model.get("id")},
                    )
                attempt = _AttemptSignal((self._options or {}).get("signal"))
                options: SimpleStreamOptions | None = (
                    {**self._options, "signal": attempt} if self._options else {"signal": attempt}  # type: ignore[typeddict-item]
                )
                try:
                    stream = await self._maybe_await(
                        owner._models.streamSimple(chain_model, self._context, options)
                    )
                    outcome = await self._consume(stream, attempt)
                except Exception as exc:  # noqa: BLE001 — StreamFn 契约：失败以消息交付
                    from earendil_works.pi_ai.api._http_stream import error_message

                    last_error = error_message(chain_model, exc)
                    outcome = _Outcome("error", [], last_error)
                if outcome.kind == "ok" and outcome.message is not None:
                    owner._active = idx  # 记忆降级后的 provider
                    for event in outcome.buffer:
                        self.push(event)
                    self.end(outcome.message)
                    return
                if outcome.kind == "timeout" and outcome.message is None:
                    from earendil_works.pi_ai.api._http_stream import error_message

                    outcome.message = error_message(
                        chain_model, TimeoutError("first packet timeout")
                    )
                    # asyncio.TimeoutError is not an httpx timeout; retain ADR
                    # 0015's structured timeout classification explicitly.
                    outcome.message["error"] = {
                        "type": "timeout",
                        "message": "first packet timeout",
                    }
                if outcome.message is not None:
                    last_error = outcome.message
                if outcome.kind != "timeout" and not _should_fallback((last_error or {}).get("error")):
                    # 客户端错误/未知/aborted：原样透出，不降级（B2）；
                    # 首包超时（B6）恒降级，无消息也切下家
                    self._deliver_error(last_error)
                    return
                if offset + 1 >= n:
                    break  # 已试完链上全部 provider → 全链失败
                owner._emit(
                    "llm.fallback_switch",
                    {
                        "fromProvider": chain_model.get("provider"),
                        "toProvider": chain[(idx + 1) % n].get("provider"),
                        "reason": "timeout" if outcome.kind == "timeout" else _error_reason(last_error),
                    },
                )
            # 全链失败：返回最后 error 消息（G8：不抛异常，pi 语义）
            if last_error is None:
                # 全部首包超时 → 合成 timeout error 消息交付
                from earendil_works.pi_ai.api._http_stream import error_message

                last_error = error_message(chain_model, TimeoutError("first packet timeout"))
            owner._emit(
                "llm.fallback_exhausted",
                {
                    "providers": [m.get("provider") for m in chain],
                    "lastProvider": last_error.get("provider"),
                    "lastErrorType": (last_error.get("error") or {}).get("type"),
                    "lastStatusCode": (last_error.get("error") or {}).get("statusCode"),
                },
            )
            self._deliver_error(last_error)
        except Exception as exc:  # noqa: BLE001 — 兜底：任何意外都以 error 消息交付
            from earendil_works.pi_ai.api._http_stream import error_message

            message = error_message(self._model, exc)
            self._deliver_error(message)

    def _deliver_error(self, message: AssistantMessage) -> None:
        reason = "aborted" if message.get("stopReason") == "aborted" else "error"
        self.push({"type": "error", "reason": reason, "error": message})
        self.end(message)

    async def _consume(
        self,
        stream: Any,
        attempt: _AttemptSignal,
    ) -> _Outcome:
        """首包探测 + 全程缓冲。B6：首个实质事件（text_start/toolcall_start/done）
        前 error 或超时 → 切下家；首包后 done 前 error → 也切下家（缓冲未交付）。
        """
        buffer: list[AssistantMessageEvent] = []
        first_packet = False
        timeout = self._owner._first_packet_timeout
        it = stream.__aiter__()
        while True:
            try:
                if not first_packet:
                    event = await asyncio.wait_for(anext(it), timeout)
                else:
                    event = await anext(it)
            except StopAsyncIteration:
                break
            except TimeoutError:
                attempt.set()  # 取消当前流再切下家
                return _Outcome("timeout", buffer, None)
            event_type = event.get("type")
            buffer.append(event)
            if event_type in _TERMINAL_EVENTS:
                message: AssistantMessage = event.get("error") or event.get("message")  # type: ignore[assignment]
                return _Outcome("ok" if event_type == "done" else "error", buffer, message)
            if not first_packet and event_type in _FIRST_PACKET_EVENTS:
                first_packet = True
        # 流结束但无终态事件：视为失败（无降级分类 → 原样透出）
        return _Outcome("error", buffer, None)


def _error_reason(message: AssistantMessage | None) -> str:
    error = (message or {}).get("error")
    if not error:
        return "unknown"
    error_type = error.get("type")
    if error_type == "http_error" and error.get("statusCode") is not None:
        return f"{error_type}:{error['statusCode']}"
    return str(error_type or "unknown")



__all__ = ["DEFAULT_FIRST_PACKET_TIMEOUT_MS", "FallbackEventSink", "FallbackStream", "_should_fallback"]
