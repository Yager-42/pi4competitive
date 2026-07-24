"""Agent class: prompt / continue / subscribe / steering / state.

upstream: packages/agent/src/agent.ts
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from earendil_works.pi_ai.types import ImageContent, Message, Model, TextContent, empty_usage

from .agent_loop import run_agent_loop, run_agent_loop_continue
from .extensions.runner import ExtensionRunner
from .stream_fn import get_default_stream_fn
from .types import (
    AfterToolCallContext,
    AfterToolCallResult,
    AgentContext,
    AgentEvent,
    AgentLoopConfig,
    AgentLoopTurnUpdate,
    AgentMessage,
    AgentTool,
    BeforeToolCallContext,
    BeforeToolCallResult,
    PrepareNextTurnContext,
    QueueMode,
    StreamFn,
    ThinkingLevel,
    ToolExecutionMode,
)

__all__ = ["AbortController", "AbortSignal", "Agent", "AgentOptions", "QueueMode"]


class AbortSignal:
    """Minimal abort signal (host delta for DOM AbortSignal)."""

    def __init__(self) -> None:
        self._aborted = False
        self._listeners: list[Callable[[], None]] = []

    @property
    def aborted(self) -> bool:
        return self._aborted

    def add_event_listener(self, _type: str, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def _abort(self) -> None:
        if self._aborted:
            return
        self._aborted = True
        for cb in list(self._listeners):
            cb()


class AbortController:
    def __init__(self) -> None:
        self.signal = AbortSignal()

    def abort(self) -> None:
        self.signal._abort()


def _default_convert_to_llm(messages: list[AgentMessage]) -> list[Message]:
    out: list[Message] = []
    for message in messages:
        if isinstance(message, dict) and message.get("role") in ("user", "assistant", "toolResult"):
            out.append(message)  # type: ignore[arg-type]
    return out


DEFAULT_MODEL: Model = {
    "id": "unknown",
    "name": "unknown",
    "api": "unknown",
    "provider": "unknown",
    "baseUrl": "",
    "reasoning": False,
    "input": [],
    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    "contextWindow": 0,
    "maxTokens": 0,
}


class _MutableAgentState:
    def __init__(
        self,
        *,
        system_prompt: str = "",
        model: Model | None = None,
        thinking_level: ThinkingLevel = "off",
        tools: list[AgentTool] | None = None,
        messages: list[AgentMessage] | None = None,
    ) -> None:
        self.systemPrompt = system_prompt
        self.model = model or DEFAULT_MODEL
        self.thinkingLevel: ThinkingLevel = thinking_level
        self._tools: list[AgentTool] = list(tools or [])
        self._messages: list[AgentMessage] = list(messages or [])
        self.isStreaming = False
        self.streamingMessage: AgentMessage | None = None
        self.pendingToolCalls: set[str] = set()
        self.errorMessage: str | None = None

    @property
    def tools(self) -> list[AgentTool]:
        return self._tools

    @tools.setter
    def tools(self, next_tools: list[AgentTool]) -> None:
        self._tools = list(next_tools)

    @property
    def messages(self) -> list[AgentMessage]:
        return self._messages

    @messages.setter
    def messages(self, next_messages: list[AgentMessage]) -> None:
        self._messages = list(next_messages)


class _PendingMessageQueue:
    def __init__(self, mode: QueueMode = "one-at-a-time") -> None:
        self.mode: QueueMode = mode
        self._messages: list[AgentMessage] = []

    def enqueue(self, message: AgentMessage) -> None:
        self._messages.append(message)

    def has_items(self) -> bool:
        return bool(self._messages)

    def drain(self) -> list[AgentMessage]:
        if self.mode == "all":
            drained = list(self._messages)
            self._messages = []
            return drained
        if not self._messages:
            return []
        first = self._messages[0]
        self._messages = self._messages[1:]
        return [first]

    def clear(self) -> None:
        self._messages = []


@dataclass
class AgentOptions:
    stream_fn: StreamFn | None = None
    initial_state: dict[str, Any] | None = None
    convert_to_llm: Callable[[list[AgentMessage]], list[Message] | Awaitable[list[Message]]] | None = None
    get_api_key: Callable[[str], Awaitable[str | None] | str | None] | None = None
    extension_runner: ExtensionRunner | None = None
    prepare_next_turn: (
        Callable[[Any | None], AgentLoopTurnUpdate | None | Awaitable[AgentLoopTurnUpdate | None]]
        | None
    ) = None
    prepare_next_turn_with_context: (
        Callable[
            [PrepareNextTurnContext, Any | None],
            AgentLoopTurnUpdate | None | Awaitable[AgentLoopTurnUpdate | None],
        ]
        | None
    ) = None
    steering_mode: QueueMode = "one-at-a-time"
    follow_up_mode: QueueMode = "one-at-a-time"
    session_id: str | None = None
    thinking_budgets: dict[str, int] | None = None
    transport: Any | None = "auto"
    max_retry_delay_ms: int | None = None
    tool_execution: ToolExecutionMode = "parallel"


@dataclass
class _ActiveRun:
    promise: asyncio.Future[None]
    abort_controller: AbortController


class Agent:
    """Stateful wrapper around the low-level agent loop."""

    def __init__(self, options: AgentOptions | None = None) -> None:
        opts = options or AgentOptions()
        initial = opts.initial_state or {}
        self._state = _MutableAgentState(
            system_prompt=str(initial.get("systemPrompt") or ""),
            model=initial.get("model") or DEFAULT_MODEL,
            thinking_level=initial.get("thinkingLevel") or "off",
            tools=initial.get("tools"),
            messages=initial.get("messages"),
        )
        self.convert_to_llm = opts.convert_to_llm or _default_convert_to_llm
        self.stream_function: StreamFn | None = opts.stream_fn or get_default_stream_fn()
        self.get_api_key = opts.get_api_key
        self.extension_runner = opts.extension_runner
        self.skills: list[Any] = []
        self.prompts: list[Any] = []
        self.prepare_next_turn = opts.prepare_next_turn
        self.prepare_next_turn_with_context = opts.prepare_next_turn_with_context
        self._steering_queue = _PendingMessageQueue(opts.steering_mode)
        self._follow_up_queue = _PendingMessageQueue(opts.follow_up_mode)
        self._listeners: list[Callable[[AgentEvent, AbortSignal], Awaitable[None] | None]] = []
        self._active_run: _ActiveRun | None = None
        self._session_started = False
        self._turn_index = 0
        self.session_id = opts.session_id
        self.thinking_budgets = opts.thinking_budgets
        self.transport = opts.transport
        self.max_retry_delay_ms = opts.max_retry_delay_ms
        self.tool_execution: ToolExecutionMode = opts.tool_execution

        if self.extension_runner:
            self.set_extension_runner(self.extension_runner)

    def subscribe(
        self, listener: Callable[[AgentEvent, AbortSignal], Awaitable[None] | None]
    ) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    @property
    def state(self) -> _MutableAgentState:
        return self._state

    @property
    def steering_mode(self) -> QueueMode:
        return self._steering_queue.mode

    @steering_mode.setter
    def steering_mode(self, mode: QueueMode) -> None:
        self._steering_queue.mode = mode

    @property
    def follow_up_mode(self) -> QueueMode:
        return self._follow_up_queue.mode

    @follow_up_mode.setter
    def follow_up_mode(self, mode: QueueMode) -> None:
        self._follow_up_queue.mode = mode

    def steer(self, message: AgentMessage) -> None:
        self._steering_queue.enqueue(message)

    def follow_up(self, message: AgentMessage) -> None:
        self._follow_up_queue.enqueue(message)

    def clear_steering_queue(self) -> None:
        self._steering_queue.clear()

    def clear_follow_up_queue(self) -> None:
        self._follow_up_queue.clear()

    def clear_all_queues(self) -> None:
        self.clear_steering_queue()
        self.clear_follow_up_queue()

    def has_queued_messages(self) -> bool:
        return self._steering_queue.has_items() or self._follow_up_queue.has_items()

    @property
    def signal(self) -> AbortSignal | None:
        if self._active_run is None:
            return None
        return self._active_run.abort_controller.signal

    def abort(self) -> None:
        if self._active_run is not None:
            self._active_run.abort_controller.abort()

    def set_extension_runner(self, runner: ExtensionRunner) -> None:
        self.extension_runner = runner

        def unavailable(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("Extension context action is not available on Agent")

        runner.bind_core(
            {
                "getActiveTools": lambda: [tool.name for tool in self._state.tools],
                "getAllTools": lambda: list(self._state.tools),
            },
            {
                "getSessionManager": lambda: None,
                "getModelRegistry": lambda: None,
                "getModel": lambda: self._state.model,
                "isIdle": lambda: self._active_run is None,
                "getSignal": lambda: self.signal,
                "abort": self.abort,
                "hasPendingMessages": self.has_queued_messages,
                "shutdown": self.abort,
                "getContextUsage": lambda: None,
                "compact": unavailable,
                "getSystemPrompt": lambda: self._state.systemPrompt,
            },
        )

    async def set_model(self, model: Model, source: str = "set") -> None:
        previous = self._state.model
        self._state.model = model
        if self.extension_runner:
            await self.extension_runner.emit(
                {"type": "model_select", "model": model, "previousModel": previous, "source": source}
            )

    async def set_thinking_level(self, level: ThinkingLevel) -> None:
        previous = self._state.thinkingLevel
        self._state.thinkingLevel = level
        if self.extension_runner:
            await self.extension_runner.emit(
                {"type": "thinking_level_select", "level": level, "previousLevel": previous}
            )

    async def shutdown_extensions(self, reason: str = "quit") -> None:
        if self.extension_runner:
            await self.extension_runner.emit({"type": "session_shutdown", "reason": reason})
            self.extension_runner.invalidate()

    async def wait_for_idle(self) -> None:
        if self._active_run is None:
            return
        await self._active_run.promise

    def reset(self) -> None:
        self._state.messages = []
        self._state.isStreaming = False
        self._state.streamingMessage = None
        self._state.pendingToolCalls = set()
        self._state.errorMessage = None
        self.clear_all_queues()

    async def prompt(
        self,
        input: str | AgentMessage | list[AgentMessage],
        images: list[ImageContent] | None = None,
    ) -> None:
        if self._active_run is not None:
            raise RuntimeError(
                "Agent is already processing a prompt. Use steer() or follow_up() to queue messages, "
                "or wait for completion."
            )
        messages = self._normalize_prompt_input(input, images)
        system_prompt = self._state.systemPrompt
        if self.extension_runner:
            if not self._session_started:
                await self.extension_runner.emit({"type": "session_start", "reason": "startup"})
                self._session_started = True
            raw_prompt = input if isinstance(input, str) else ""
            before = await self.extension_runner.emit_before_agent_start(
                raw_prompt, images, system_prompt, {"cwd": self.extension_runner.cwd}
            )
            if before and before.get("systemPrompt") is not None:
                system_prompt = before["systemPrompt"]
        await self._run_prompt_messages(messages, system_prompt=system_prompt)

    async def continue_(self) -> None:
        """Continue from current transcript (``continue`` is a Python keyword)."""
        if self._active_run is not None:
            raise RuntimeError("Agent is already processing. Wait for completion before continuing.")

        if not self._state.messages:
            raise RuntimeError("No messages to continue from")

        last = self._state.messages[-1]
        role = last.get("role") if isinstance(last, dict) else None
        if role == "assistant":
            queued_steering = self._steering_queue.drain()
            if queued_steering:
                await self._run_prompt_messages(queued_steering, skip_initial_steering_poll=True)
                return
            queued_follow_ups = self._follow_up_queue.drain()
            if queued_follow_ups:
                await self._run_prompt_messages(queued_follow_ups)
                return
            raise RuntimeError("Cannot continue from message role: assistant")

        await self._run_continuation()

    # Alias matching upstream name for callers that prefer it via getattr
    continue_run = continue_

    def _normalize_prompt_input(
        self,
        input: str | AgentMessage | list[AgentMessage],
        images: list[ImageContent] | None,
    ) -> list[AgentMessage]:
        if isinstance(input, list):
            return list(input)
        if not isinstance(input, str):
            return [input]
        content: list[TextContent | ImageContent] = [{"type": "text", "text": input}]
        if images:
            content.extend(images)
        return [{"role": "user", "content": content, "timestamp": int(time.time() * 1000)}]

    async def _run_prompt_messages(
        self,
        messages: list[AgentMessage],
        *,
        skip_initial_steering_poll: bool = False,
        system_prompt: str | None = None,
    ) -> None:
        async def executor(signal: AbortSignal) -> None:
            if self.stream_function is None:
                raise RuntimeError("stream_fn is required (or set_default_stream_fn)")
            context = self._create_context_snapshot()
            if system_prompt is not None:
                context["systemPrompt"] = system_prompt
            await run_agent_loop(
                messages,
                context,
                self._create_loop_config(skip_initial_steering_poll=skip_initial_steering_poll),
                self._process_events,
                signal,
                self.stream_function,
            )

        await self._run_with_lifecycle(executor)

    async def _run_continuation(self) -> None:
        async def executor(signal: AbortSignal) -> None:
            if self.stream_function is None:
                raise RuntimeError("stream_fn is required (or set_default_stream_fn)")
            await run_agent_loop_continue(
                self._create_context_snapshot(),
                self._create_loop_config(),
                self._process_events,
                signal,
                self.stream_function,
            )

        await self._run_with_lifecycle(executor)

    def _create_context_snapshot(self) -> AgentContext:
        return {
            "systemPrompt": self._state.systemPrompt,
            "messages": list(self._state.messages),
            "tools": list(self._state.tools),
        }

    def _create_loop_config(self, *, skip_initial_steering_poll: bool = False) -> AgentLoopConfig:
        skip = skip_initial_steering_poll

        async def get_steering() -> list[AgentMessage]:
            nonlocal skip
            if skip:
                skip = False
                return []
            return self._steering_queue.drain()

        async def get_follow_up() -> list[AgentMessage]:
            return self._follow_up_queue.drain()

        async def prepare_next(context: PrepareNextTurnContext) -> AgentLoopTurnUpdate | None:
            if self.prepare_next_turn_with_context:
                result = self.prepare_next_turn_with_context(context, self.signal)
                if asyncio.iscoroutine(result) or isinstance(result, Awaitable):
                    return await result  # type: ignore[misc]
                return result
            if self.prepare_next_turn:
                result = self.prepare_next_turn(self.signal)
                if asyncio.iscoroutine(result) or isinstance(result, Awaitable):
                    return await result  # type: ignore[misc]
                return result
            return None

        thinking = self._state.thinkingLevel
        runner = self.extension_runner

        async def before_tool_call(context: BeforeToolCallContext, _signal: Any) -> Any:
            if not runner:
                return None
            call = context["toolCall"]
            return await runner.emit_tool_call(
                {"type": "tool_call", "toolCallId": call["id"], "toolName": call["name"], "input": context["args"]}
            )

        async def after_tool_call(context: AfterToolCallContext, _signal: Any) -> Any:
            if not runner:
                return None
            call, result = context["toolCall"], context["result"]
            return await runner.emit_tool_result(
                {"type": "tool_result", "toolCallId": call["id"], "toolName": call["name"],
                 "input": context["args"], "content": result.get("content", []),
                 "details": result.get("details"), "isError": context["isError"],
                 "usage": result.get("usage")}
            )

        async def on_payload(payload: Any, _model: Any) -> Any:
            return await runner.emit_before_provider_request(payload) if runner else payload

        async def on_response(response: dict[str, Any], _model: Any) -> None:
            if runner:
                await runner.emit({"type": "after_provider_response", **response})

        return AgentLoopConfig(
            model=self._state.model,
            convertToLlm=self.convert_to_llm,
            transformContext=(lambda messages, _signal: runner.emit_context(messages)) if runner else None,
            getApiKey=self.get_api_key,
            beforeToolCall=before_tool_call if runner else None,
            afterToolCall=after_tool_call if runner else None,
            beforeProviderHeaders=runner.emit_before_provider_headers if runner else None,
            prepareNextTurn=(prepare_next if (self.prepare_next_turn or self.prepare_next_turn_with_context) else None),
            getSteeringMessages=get_steering,
            getFollowUpMessages=get_follow_up,
            toolExecution=self.tool_execution,
            sessionId=self.session_id,
            onPayload=on_payload if runner else None,
            onResponse=on_response if runner else None,
            transport=self.transport,
            thinkingBudgets=self.thinking_budgets,
            maxTokens=None,
            reasoning=None if thinking == "off" else thinking,
        )

    async def _run_with_lifecycle(
        self, executor: Callable[[AbortSignal], Awaitable[None]]
    ) -> None:
        if self._active_run is not None:
            raise RuntimeError("Agent is already processing.")

        abort_controller = AbortController()
        loop = asyncio.get_running_loop()
        promise: asyncio.Future[None] = loop.create_future()
        self._active_run = _ActiveRun(promise=promise, abort_controller=abort_controller)

        self._state.isStreaming = True
        self._state.streamingMessage = None
        self._state.errorMessage = None

        try:
            await executor(abort_controller.signal)
        except Exception as error:  # noqa: BLE001
            await self._handle_run_failure(error, abort_controller.signal.aborted)
        finally:
            if self.extension_runner:
                await self.extension_runner.emit({"type": "agent_settled"})
            self._finish_run()

    async def _handle_run_failure(self, error: Any, aborted: bool) -> None:
        failure_message: AgentMessage = {
            "role": "assistant",
            "content": [{"type": "text", "text": ""}],
            "api": self._state.model.get("api", "unknown"),
            "provider": self._state.model.get("provider", "unknown"),
            "model": self._state.model.get("id", "unknown"),
            "usage": empty_usage(),
            "stopReason": "aborted" if aborted else "error",
            "errorMessage": str(error),
            "timestamp": int(time.time() * 1000),
        }
        await self._process_events({"type": "message_start", "message": failure_message})
        await self._process_events({"type": "message_end", "message": failure_message})
        await self._process_events(
            {"type": "turn_end", "message": failure_message, "toolResults": []}
        )
        await self._process_events({"type": "agent_end", "messages": [failure_message]})

    def _finish_run(self) -> None:
        self._state.isStreaming = False
        self._state.streamingMessage = None
        self._state.pendingToolCalls = set()
        if self._active_run is not None:
            if not self._active_run.promise.done():
                self._active_run.promise.set_result(None)
        self._active_run = None

    async def _process_events(self, event: AgentEvent) -> None:
        et = event["type"]
        if self.extension_runner:
            if et == "turn_start":
                event["turnIndex"] = self._turn_index  # type: ignore[index]
                event["timestamp"] = int(time.time() * 1000)  # type: ignore[index]
                self._turn_index += 1
                await self.extension_runner.emit(dict(event))
            elif et == "message_end":
                original = event["message"]  # type: ignore[index]
                replacement = await self.extension_runner.emit_message_end(event)
                if replacement is not None and isinstance(original, dict):
                    original.clear()
                    original.update(replacement)
                    event["message"] = original  # type: ignore[index]
            else:
                await self.extension_runner.emit(dict(event))
        if et == "message_start":
            self._state.streamingMessage = event["message"]  # type: ignore[index]
        elif et == "message_update":
            self._state.streamingMessage = event["message"]  # type: ignore[index]
        elif et == "message_end":
            self._state.streamingMessage = None
            self._state.messages.append(event["message"])  # type: ignore[index]
        elif et == "tool_execution_start":
            pending = set(self._state.pendingToolCalls)
            pending.add(event["toolCallId"])  # type: ignore[index]
            self._state.pendingToolCalls = pending
        elif et == "tool_execution_end":
            pending = set(self._state.pendingToolCalls)
            pending.discard(event["toolCallId"])  # type: ignore[index]
            self._state.pendingToolCalls = pending
        elif et == "turn_end":
            msg = event.get("message")  # type: ignore[assignment]
            if isinstance(msg, dict) and msg.get("role") == "assistant" and msg.get("errorMessage"):
                self._state.errorMessage = str(msg["errorMessage"])
        elif et == "agent_end":
            self._state.streamingMessage = None

        if self._active_run is None:
            raise RuntimeError("Agent listener invoked outside active run")
        signal = self._active_run.abort_controller.signal
        for listener in list(self._listeners):
            result = listener(event, signal)
            if asyncio.iscoroutine(result) or isinstance(result, Awaitable):
                await result  # type: ignore[misc]
