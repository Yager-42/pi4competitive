"""JournalStream — StreamFn wrapper: 每次 LLM 调用产 ``llm.request``/``llm.response``。

为什么在 stream_fn 层（非 extension 事件）：本仓 pi_agent port 的 agent loop
（``agent_loop.py _stream_assistant_response``）**不调用** ``config.onPayload`` /
``onResponse``（上游 TS 有、Python port 未接），因此 ``before_provider_request`` /
``after_provider_response`` extension 事件在此 port 永不触发。``packages/agent``
零 diff（D3/D8）约束下，llm.* 事件改在 **stream_fn 单点**产出 —— 所有 harness
LLM 调用（主 harness / ephemeral sub-agent）必经此处，与 JournalBridge 的
``agent.*``/``tool.*`` 事件互补。

行为（feature llm-fallback-observability-v1 §3.3 语义）：
- ``llm.request``：调用入口写（payload.model = 实际 model id）；
- ``llm.response``：流终态（done/error）后写（status = ok/error）；
- 事件顺序：request < 全部流事件 < response；journal 失败不阻断流（guarded_append）。
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from earendil_works.pi_ai.api._http_stream import error_message
from earendil_works.pi_ai.types import (
    AssistantMessage,
    AssistantMessageEvent,
    Context,
    Model,
    SimpleStreamOptions,
)
from earendil_works.pi_ai.utils.event_stream import AssistantMessageEventStream

_TERMINAL_EVENTS = frozenset({"done", "error"})
_OPTIONS_TO_STRIP = frozenset({"signal", "sessionId", "transport"})


def _sanitize_options(options: SimpleStreamOptions | None) -> SimpleStreamOptions | None:
    """剥离 harness 注入的 signal/sessionId/transport。

    实测（deepseek-v3.2 via chatanywhere）：这些字段经 harness 传入时会让流变慢
    甚至不产出 toolcall（A1/A2 search 都受影响）；剥离后 streamSimple 稳定调工具。
    """
    if not options:
        return options
    return {k: v for k, v in options.items() if k not in _OPTIONS_TO_STRIP}


def _sanitize_context(context: Context) -> Context:
    """消息里的 ``timestamp`` 字段（pi Message 附带）可能干扰工具调用，转发前剥掉。"""
    messages = context.get("messages")
    if not isinstance(messages, list) or not any(
        isinstance(m, dict) and "timestamp" in m for m in messages
    ):
        return context
    return {
        **context,
        "messages": [
            {k: v for k, v in m.items() if k != "timestamp"} if isinstance(m, dict) else m
            for m in messages
        ],
    }


class JournalStream:
    """StreamFn 兼容包装：透传事件，另写 llm.request/llm.response journal 事件。

    ``append(event_type, payload)`` 由 wiring 注入（guarded_append +
    ``current_run_journal`` ContextVar 解析当前 run；run 外静默 no-op）。
    """

    def __init__(
        self,
        stream_fn: Any,
        append: Callable[[str, dict[str, Any]], None],
    ) -> None:
        self._stream_fn = stream_fn
        self._append = append

    def __call__(
        self,
        model: Model,
        context: Context,
        options: SimpleStreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        self._append(
            "llm.request",
            {"model": model.get("id"), "provider": model.get("provider")},
        )
        return _JournalCall(self, model, context, options)


class _JournalCall(AssistantMessageEventStream):
    """单次调用的包装流：缓冲内层流事件，终态后写 llm.response 再交付。

    与 ``lazy_stream`` / ``_FallbackCall`` 同款 setup 模式：有运行 loop 直接建
    task，否则推迟到首次迭代。
    """

    def __init__(
        self,
        owner: JournalStream,
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
        model = self._model
        buffer: list[AssistantMessageEvent] = []
        final_message: AssistantMessage | None = None
        status = "ok"
        try:
            stream = await self._maybe_await(
                self._owner._stream_fn(
                    model, _sanitize_context(self._context), _sanitize_options(self._options)
                )
            )
            async for event in stream:
                event_type = event.get("type")
                buffer.append(event)
                if event_type in _TERMINAL_EVENTS:
                    final_message = event.get("error") or event.get("message")  # type: ignore[assignment]
                    if event_type == "error":
                        status = "error"
                    break
            if status == "error" and final_message is None:
                # 终态 error 但无消息：用 error_message 合成（StreamFn 契约）。
                final_message = error_message(model, "stream ended with error")
        except Exception as exc:  # noqa: BLE001 — StreamFn 契约：失败以消息交付
            status = "error"
            final_message = error_message(model, exc)
            buffer = [{"type": "error", "reason": "error", "error": final_message}]
        finally:
            usage = (final_message or {}).get("usage") if final_message is not None else None
            payload: dict[str, Any] = {
                "model": model.get("id"),
                "status": status,
                "errorType": (final_message.get("error") or {}).get("type")
                if final_message is not None
                else None,
            }
            if isinstance(usage, dict) and usage:
                # operations collector 据此汇总 prompt/completion tokens 与 cost
                payload["usage"] = usage
            self._owner._append("llm.response", payload)
        if final_message is not None:
            for event in buffer:
                self.push(event)
            self.end(final_message)
        else:
            # 流无终态事件：交付空 done（pi 语义容错）。
            self.end(
                {
                    "role": "assistant",
                    "content": [],
                    "api": model.get("api", "unknown"),
                    "provider": model.get("provider", ""),
                    "model": model.get("id", ""),
                    "usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    "stopReason": "stop",
                }
            )


__all__ = ["JournalStream"]
