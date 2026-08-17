"""Eval-local StreamFn wrapper: LLM 调用 → ``llm.request`` / ``llm.response`` journal 事件.

Standalone mirror of ``competitive_app.application.model.journal_stream.JournalStream``
（stream_fn 单点产出 llm.* 事件）—— A1 服务不 import competitive_app，故在 eval 内
复刻同语义：

- ``llm.request``：调用入口写（payload.model = 实际 model id）；
- ``llm.response``：流终态（done/error）后写（status = ok/error，payload.usage =
  assistant message 的 usage，供 operations collector 汇总 token/cost）；
- 事件顺序：request < 全部流事件 < response；journal 失败不阻断流（append_safe）。

为什么子类化 ``AssistantMessageEventStream``（而非裸 async generator）：agent loop
（``agent_loop._stream_assistant_response``）在 done/error 后调用
``await response.result()``，bare generator 没有 ``.result()`` 会抛 AttributeError、
被 agent loop 吞掉 → 只留空 partial 消息。子类化保留 ``push/end/result/await_result``
语义，与 competitive_app 的 JournalStream 行为一致（在线验证过）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable
from typing import Any

from earendil_works.pi_ai.types import (
    AssistantMessage,
    AssistantMessageEvent,
    Context,
    Model,
    SimpleStreamOptions,
)
from earendil_works.pi_ai.utils.event_stream import AssistantMessageEventStream

from .run_journal import RunJournal

_TERMINAL_EVENTS = frozenset({"done", "error"})
_OPTIONS_TO_STRIP = frozenset({"signal", "sessionId", "transport"})


def _sanitize_options(options: SimpleStreamOptions | None) -> SimpleStreamOptions | None:
    """剥离 harness 注入的 signal/sessionId/transport。

    实测（deepseek-v3.2 via chatanywhere）：这些字段经 harness 传入时会让流变慢
    甚至不产出 toolcall（A1 run 里 5/5 case 零工具调用）；剥离后直连 streamSimple
    稳定调工具。对 eval A1 无 abort 需求，signal 可安全丢弃。
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


class EvalJournalStream:
    """StreamFn 兼容包装：透传事件，另写 llm.request/llm.response journal 事件。"""

    def __init__(self, stream_fn: Any, journal: RunJournal) -> None:
        self._stream_fn = stream_fn
        self._journal = journal

    def __call__(
        self,
        model: Model,
        context: Context,
        options: SimpleStreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        self._journal.append_safe(
            "llm.request",
            {"model": model.get("id"), "provider": model.get("provider")},
        )
        return _JournalCall(self, model, context, options)


class _JournalCall(AssistantMessageEventStream):
    """单次调用的包装流：缓冲内层流事件，终态后写 llm.response 再交付。

    与 competitive_app JournalStream._JournalCall 同款 setup 模式：有运行 loop
    直接建 task，否则推迟到首次迭代。
    """

    def __init__(
        self,
        owner: EvalJournalStream,
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
                self._owner._stream_fn(model, _sanitize_context(self._context), _sanitize_options(self._options))
            )
            async for event in stream:
                event_type = event.get("type")
                buffer.append(event)
                if event_type in _TERMINAL_EVENTS:
                    final_message = event.get("error") or event.get("message")  # type: ignore[assignment]
                    if event_type == "error":
                        status = "error"
                    break
        except Exception:  # noqa: BLE001 — StreamFn 契约：失败以消息交付
            status = "error"
            buffer = [{"type": "error", "reason": "error", "error": final_message}]
        finally:
            self._owner._journal.append_safe(
                "llm.response",
                _response_payload(model, status, final_message),
            )
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


def _response_payload(
    model: Model, status: str, final_message: AssistantMessage | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model.get("id"),
        "provider": model.get("provider"),
        "status": status,
    }
    if status == "error" and isinstance(final_message, dict):
        error = final_message.get("error")
        if isinstance(error, dict) and error.get("type"):
            payload["errorType"] = error.get("type")
    if isinstance(final_message, dict) and isinstance(final_message.get("usage"), dict):
        usage = final_message["usage"]
        if usage:
            payload["usage"] = usage
    return payload


__all__ = ["EvalJournalStream"]
