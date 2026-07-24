"""Agent loop: LLM turns + tool execution.

upstream: packages/agent/src/agent-loop.ts
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, Literal, TypedDict, cast

from earendil_works.pi_ai.types import (
    AssistantMessage,
    Context,
    Message,
    ToolResultMessage,
)
from earendil_works.pi_ai.utils.event_stream import EventStream
from earendil_works.pi_ai.utils.validation import validate_tool_arguments

from .stream_fn import get_default_stream_fn
from .types import (
    AgentContext,
    AgentEvent,
    AgentEventSink,
    AgentLoopConfig,
    AgentMessage,
    AgentTool,
    AgentToolCall,
    AgentToolResult,
    StreamFn,
)

__all__ = [
    "AgentEventSink",
    "agent_loop",
    "agent_loop_continue",
    "run_agent_loop",
    "run_agent_loop_continue",
]


def _is_aborted(signal: Any | None) -> bool:
    if signal is None:
        return False
    aborted = getattr(signal, "aborted", None)
    if aborted is not None:
        return bool(aborted)
    is_set = getattr(signal, "is_set", None)
    if callable(is_set):
        return bool(is_set())
    return False


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value) or isinstance(value, Awaitable):
        return await value  # type: ignore[misc]
    return value


async def _emit(emit: AgentEventSink, event: AgentEvent) -> None:
    result = emit(event)
    if asyncio.iscoroutine(result) or isinstance(result, Awaitable):
        await result  # type: ignore[misc]


def create_agent_stream() -> EventStream[AgentEvent, list[AgentMessage]]:
    return EventStream(
        lambda event: event["type"] == "agent_end",
        lambda event: event["messages"] if event["type"] == "agent_end" else [],  # type: ignore[return-value]
    )


def agent_loop(
    prompts: list[AgentMessage],
    context: AgentContext,
    config: AgentLoopConfig,
    signal: Any | None,
    stream_fn: StreamFn | None,
) -> EventStream[AgentEvent, list[AgentMessage]]:
    """Start an agent loop with new prompt messages. Events push into the returned stream."""
    stream = create_agent_stream()

    async def _run() -> None:
        messages = await run_agent_loop(prompts, context, config, stream.push, signal, stream_fn)
        stream.end(messages)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        # No running loop — caller must drive via run_agent_loop / await_result after scheduling.
        stream._pending_run = _run  # type: ignore[attr-defined]

    return stream


def agent_loop_continue(
    context: AgentContext,
    config: AgentLoopConfig,
    signal: Any | None,
    stream_fn: StreamFn | None,
) -> EventStream[AgentEvent, list[AgentMessage]]:
    """Continue without adding a new user message. Last message must not be assistant."""
    if not context.get("messages"):
        raise ValueError("Cannot continue: no messages in context")
    last = context["messages"][-1]
    role = last.get("role") if isinstance(last, dict) else getattr(last, "role", None)
    if role == "assistant":
        raise ValueError("Cannot continue from message role: assistant")

    stream = create_agent_stream()

    async def _run() -> None:
        messages = await run_agent_loop_continue(context, config, stream.push, signal, stream_fn)
        stream.end(messages)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        stream._pending_run = _run  # type: ignore[attr-defined]

    return stream


async def run_agent_loop(
    prompts: list[AgentMessage],
    context: AgentContext,
    config: AgentLoopConfig,
    emit: AgentEventSink,
    signal: Any | None,
    stream_fn: StreamFn | None,
) -> list[AgentMessage]:
    new_messages: list[AgentMessage] = list(prompts)
    current_context: AgentContext = {
        "systemPrompt": context.get("systemPrompt", ""),
        "messages": [*context.get("messages", []), *prompts],
    }
    if "tools" in context:
        current_context["tools"] = context["tools"]

    await _emit(emit, {"type": "agent_start"})
    await _emit(emit, {"type": "turn_start"})
    for prompt in prompts:
        await _emit(emit, {"type": "message_start", "message": prompt})
        await _emit(emit, {"type": "message_end", "message": prompt})

    resolved = stream_fn or get_default_stream_fn()
    if resolved is None:
        raise ValueError("stream_fn is required (or set_default_stream_fn)")
    await _run_loop(current_context, new_messages, config, signal, emit, resolved)
    return new_messages


async def run_agent_loop_continue(
    context: AgentContext,
    config: AgentLoopConfig,
    emit: AgentEventSink,
    signal: Any | None,
    stream_fn: StreamFn | None,
) -> list[AgentMessage]:
    if not context.get("messages"):
        raise ValueError("Cannot continue: no messages in context")
    last = context["messages"][-1]
    role = last.get("role") if isinstance(last, dict) else getattr(last, "role", None)
    if role == "assistant":
        raise ValueError("Cannot continue from message role: assistant")

    new_messages: list[AgentMessage] = []
    current_context: AgentContext = {
        "systemPrompt": context.get("systemPrompt", ""),
        "messages": list(context.get("messages", [])),
    }
    if "tools" in context:
        current_context["tools"] = context["tools"]

    await _emit(emit, {"type": "agent_start"})
    await _emit(emit, {"type": "turn_start"})

    resolved = stream_fn or get_default_stream_fn()
    if resolved is None:
        raise ValueError("stream_fn is required (or set_default_stream_fn)")
    await _run_loop(current_context, new_messages, config, signal, emit, resolved)
    return new_messages


async def _run_loop(
    initial_context: AgentContext,
    new_messages: list[AgentMessage],
    initial_config: AgentLoopConfig,
    signal: Any | None,
    emit: AgentEventSink,
    stream_function: StreamFn,
) -> None:
    current_context = initial_context
    config = initial_config
    first_turn = True
    pending_messages: list[AgentMessage] = []
    if config.getSteeringMessages:
        pending_messages = list(await _maybe_await(config.getSteeringMessages()))

    while True:
        has_more_tool_calls = True

        while has_more_tool_calls or pending_messages:
            if not first_turn:
                await _emit(emit, {"type": "turn_start"})
            else:
                first_turn = False

            if pending_messages:
                for message in pending_messages:
                    await _emit(emit, {"type": "message_start", "message": message})
                    await _emit(emit, {"type": "message_end", "message": message})
                    current_context["messages"].append(message)
                    new_messages.append(message)
                pending_messages = []

            message = await _stream_assistant_response(
                current_context, config, signal, emit, stream_function
            )
            new_messages.append(message)

            stop = message.get("stopReason")
            if stop in ("error", "aborted"):
                await _emit(emit, {"type": "turn_end", "message": message, "toolResults": []})
                await _emit(emit, {"type": "agent_end", "messages": new_messages})
                return

            tool_calls = [
                c
                for c in message.get("content") or []
                if isinstance(c, dict) and c.get("type") == "toolCall"
            ]
            tool_results: list[ToolResultMessage] = []
            has_more_tool_calls = False
            if tool_calls:
                if stop == "length":
                    executed = await _fail_tool_calls_from_truncated(cast(list[AgentToolCall], tool_calls), emit)
                else:
                    executed = await _execute_tool_calls(
                        current_context, message, config, signal, emit
                    )
                tool_results.extend(executed["messages"])
                has_more_tool_calls = not executed["terminate"]
                for result in tool_results:
                    current_context["messages"].append(result)
                    new_messages.append(result)

            await _emit(emit, {"type": "turn_end", "message": message, "toolResults": tool_results})

            next_ctx = {
                "message": message,
                "toolResults": tool_results,
                "context": current_context,
                "newMessages": new_messages,
            }
            if config.prepareNextTurn:
                snapshot = await _maybe_await(config.prepareNextTurn(next_ctx))  # type: ignore[arg-type]
                if snapshot:
                    if "context" in snapshot and snapshot["context"] is not None:
                        current_context = snapshot["context"]
                    new_model = snapshot.get("model")
                    thinking = snapshot.get("thinkingLevel")
                    if new_model is not None or thinking is not None:
                        config = replace(
                            config,
                            model=new_model if new_model is not None else config.model,
                            reasoning=(
                                config.reasoning
                                if thinking is None
                                else (None if thinking == "off" else thinking)
                            ),
                        )

            if config.shouldStopAfterTurn:
                stop_after = await _maybe_await(
                    config.shouldStopAfterTurn(
                        {
                            "message": message,
                            "toolResults": tool_results,
                            "context": current_context,
                            "newMessages": new_messages,
                        }
                    )
                )
                if stop_after:
                    await _emit(emit, {"type": "agent_end", "messages": new_messages})
                    return

            if config.getSteeringMessages:
                pending_messages = list(await _maybe_await(config.getSteeringMessages()))
            else:
                pending_messages = []

        if config.getFollowUpMessages:
            follow_ups = list(await _maybe_await(config.getFollowUpMessages()))
            if follow_ups:
                pending_messages = follow_ups
                continue
        break

    await _emit(emit, {"type": "agent_end", "messages": new_messages})


async def _stream_assistant_response(
    context: AgentContext,
    config: AgentLoopConfig,
    signal: Any | None,
    emit: AgentEventSink,
    stream_function: StreamFn,
) -> AssistantMessage:
    messages: list[AgentMessage] = list(context.get("messages") or [])
    if config.transformContext:
        messages = list(await _maybe_await(config.transformContext(messages, signal)))

    llm_messages: list[Message] = list(await _maybe_await(config.convertToLlm(messages)))

    llm_tools = None
    if context.get("tools") is not None:
        llm_tools = [t.to_llm_tool() for t in context["tools"] or []]

    llm_context: Context = {
        "systemPrompt": context.get("systemPrompt", ""),
        "messages": llm_messages,
    }
    if llm_tools is not None:
        llm_context["tools"] = llm_tools

    resolved_api_key = config.apiKey
    if config.getApiKey:
        key = await _maybe_await(config.getApiKey(str(config.model.get("provider", ""))))
        if key:
            resolved_api_key = key

    stream_opts = config.to_stream_options()
    if resolved_api_key is not None:
        stream_opts["apiKey"] = resolved_api_key
    if signal is not None:
        stream_opts["signal"] = signal
    if config.beforeProviderHeaders:
        headers = dict(stream_opts.get("headers") or {})
        stream_opts["headers"] = await _maybe_await(config.beforeProviderHeaders(headers))  # type: ignore[typeddict-item]

    response = stream_function(config.model, llm_context, stream_opts)
    response = await _maybe_await(response)

    partial_message: AssistantMessage | None = None
    added_partial = False

    async for event in response:
        et = event.get("type")
        if et == "start":
            partial_message = event.get("partial")  # type: ignore[assignment]
            if partial_message is not None:
                context["messages"].append(partial_message)
                added_partial = True
                await _emit(emit, {"type": "message_start", "message": {**partial_message}})
        elif et in (
            "text_start",
            "text_delta",
            "text_end",
            "thinking_start",
            "thinking_delta",
            "thinking_end",
            "toolcall_start",
            "toolcall_delta",
            "toolcall_end",
        ):
            if partial_message is not None:
                partial_message = event.get("partial")  # type: ignore[assignment]
                if partial_message is not None:
                    context["messages"][-1] = partial_message
                    await _emit(
                        emit,
                        {
                            "type": "message_update",
                            "assistantMessageEvent": event,
                            "message": {**partial_message},
                        },
                    )
        elif et in ("done", "error"):
            final_message = await response.result()
            if added_partial:
                context["messages"][-1] = final_message
            else:
                context["messages"].append(final_message)
            if not added_partial:
                await _emit(emit, {"type": "message_start", "message": {**final_message}})
            await _emit(emit, {"type": "message_end", "message": final_message})
            return final_message

    final_message = await response.result()
    if added_partial:
        context["messages"][-1] = final_message
    else:
        context["messages"].append(final_message)
        await _emit(emit, {"type": "message_start", "message": {**final_message}})
    await _emit(emit, {"type": "message_end", "message": final_message})
    return final_message


class _ExecutedToolCallBatch(TypedDict):
    messages: list[ToolResultMessage]
    terminate: bool


class _PreparedToolCall(TypedDict):
    kind: Literal["prepared"]
    toolCall: AgentToolCall
    tool: AgentTool
    args: Any


class _ImmediateToolCallOutcome(TypedDict):
    kind: Literal["immediate"]
    result: AgentToolResult
    isError: bool


class _ExecutedToolCallOutcome(TypedDict):
    result: AgentToolResult
    isError: bool


class _FinalizedToolCallOutcome(TypedDict):
    toolCall: AgentToolCall
    result: AgentToolResult
    isError: bool


async def _fail_tool_calls_from_truncated(
    tool_calls: list[AgentToolCall],
    emit: AgentEventSink,
) -> _ExecutedToolCallBatch:
    messages: list[ToolResultMessage] = []
    for tool_call in tool_calls:
        await _emit(
            emit,
            {
                "type": "tool_execution_start",
                "toolCallId": tool_call["id"],
                "toolName": tool_call["name"],
                "args": tool_call.get("arguments"),
            },
        )
        finalized: _FinalizedToolCallOutcome = {
            "toolCall": tool_call,
            "result": _create_error_tool_result(
                f'Tool call "{tool_call["name"]}" was not executed: the response hit the output '
                "token limit, so its arguments may be truncated. Re-issue the tool call with complete arguments."
            ),
            "isError": True,
        }
        await _emit_tool_execution_end(finalized, emit)
        tool_result_message = _create_tool_result_message(finalized)
        await _emit_tool_result_message(tool_result_message, emit)
        messages.append(tool_result_message)
    return {"messages": messages, "terminate": False}


async def _execute_tool_calls(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    config: AgentLoopConfig,
    signal: Any | None,
    emit: AgentEventSink,
) -> _ExecutedToolCallBatch:
    tool_calls = [
        cast(AgentToolCall, c)
        for c in assistant_message.get("content") or []
        if isinstance(c, dict) and c.get("type") == "toolCall"
    ]
    tools = current_context.get("tools") or []
    tool_by_name = {t.name: t for t in tools}
    has_sequential = any(
        (tool_by_name.get(tc["name"]) is not None)
        and tool_by_name[tc["name"]].executionMode == "sequential"
        for tc in tool_calls
    )
    if config.toolExecution == "sequential" or has_sequential:
        return await _execute_tool_calls_sequential(
            current_context, assistant_message, tool_calls, config, signal, emit
        )
    return await _execute_tool_calls_parallel(
        current_context, assistant_message, tool_calls, config, signal, emit
    )


async def _execute_tool_calls_sequential(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    tool_calls: list[AgentToolCall],
    config: AgentLoopConfig,
    signal: Any | None,
    emit: AgentEventSink,
) -> _ExecutedToolCallBatch:
    finalized_calls: list[_FinalizedToolCallOutcome] = []
    messages: list[ToolResultMessage] = []

    for tool_call in tool_calls:
        await _emit(
            emit,
            {
                "type": "tool_execution_start",
                "toolCallId": tool_call["id"],
                "toolName": tool_call["name"],
                "args": tool_call.get("arguments"),
            },
        )
        preparation = await _prepare_tool_call(
            current_context, assistant_message, tool_call, config, signal
        )
        if preparation["kind"] == "immediate":
            finalized: _FinalizedToolCallOutcome = {
                "toolCall": tool_call,
                "result": preparation["result"],
                "isError": preparation["isError"],
            }
        else:
            executed = await _execute_prepared_tool_call(preparation, signal, emit)
            finalized = await _finalize_executed_tool_call(
                current_context,
                assistant_message,
                preparation,
                executed,
                config,
                signal,
            )

        await _emit_tool_execution_end(finalized, emit)
        tool_result_message = _create_tool_result_message(finalized)
        await _emit_tool_result_message(tool_result_message, emit)
        finalized_calls.append(finalized)
        messages.append(tool_result_message)

        if _is_aborted(signal):
            break

    return {
        "messages": messages,
        "terminate": _should_terminate_tool_batch(finalized_calls),
    }


async def _execute_tool_calls_parallel(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    tool_calls: list[AgentToolCall],
    config: AgentLoopConfig,
    signal: Any | None,
    emit: AgentEventSink,
) -> _ExecutedToolCallBatch:
    finalized_entries: list[_FinalizedToolCallOutcome | Callable[[], Awaitable[_FinalizedToolCallOutcome]]] = []

    for tool_call in tool_calls:
        await _emit(
            emit,
            {
                "type": "tool_execution_start",
                "toolCallId": tool_call["id"],
                "toolName": tool_call["name"],
                "args": tool_call.get("arguments"),
            },
        )
        preparation = await _prepare_tool_call(
            current_context, assistant_message, tool_call, config, signal
        )
        if preparation["kind"] == "immediate":
            finalized: _FinalizedToolCallOutcome = {
                "toolCall": tool_call,
                "result": preparation["result"],
                "isError": preparation["isError"],
            }
            await _emit_tool_execution_end(finalized, emit)
            finalized_entries.append(finalized)
            if _is_aborted(signal):
                break
            continue

        prep = preparation

        async def _run(prep: _PreparedToolCall = prep) -> _FinalizedToolCallOutcome:  # type: ignore[misc]
            executed = await _execute_prepared_tool_call(prep, signal, emit)
            finalized_inner = await _finalize_executed_tool_call(
                current_context,
                assistant_message,
                prep,
                executed,
                config,
                signal,
            )
            await _emit_tool_execution_end(finalized_inner, emit)
            return finalized_inner

        finalized_entries.append(_run)
        if _is_aborted(signal):
            break

    ordered = await asyncio.gather(
        *[
            entry() if callable(entry) else asyncio.sleep(0, result=entry)
            for entry in finalized_entries
        ]
    )
    ordered_finalized = cast(list[_FinalizedToolCallOutcome], list(ordered))
    messages: list[ToolResultMessage] = []
    for finalized in ordered_finalized:
        tool_result_message = _create_tool_result_message(finalized)
        await _emit_tool_result_message(tool_result_message, emit)
        messages.append(tool_result_message)

    return {
        "messages": messages,
        "terminate": _should_terminate_tool_batch(ordered_finalized),
    }


def _should_terminate_tool_batch(finalized_calls: list[_FinalizedToolCallOutcome]) -> bool:
    return bool(finalized_calls) and all(
        f["result"].get("terminate") is True for f in finalized_calls
    )


def _prepare_tool_call_arguments(tool: AgentTool, tool_call: AgentToolCall) -> AgentToolCall:
    if not tool.prepareArguments:
        return tool_call
    prepared = tool.prepareArguments(tool_call.get("arguments"))
    if prepared is tool_call.get("arguments"):
        return tool_call
    updated = dict(tool_call)
    updated["arguments"] = prepared
    return cast(AgentToolCall, updated)


async def _prepare_tool_call(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    tool_call: AgentToolCall,
    config: AgentLoopConfig,
    signal: Any | None,
) -> _PreparedToolCall | _ImmediateToolCallOutcome:
    tools = current_context.get("tools") or []
    tool = next((t for t in tools if t.name == tool_call["name"]), None)
    if tool is None:
        return {
            "kind": "immediate",
            "result": _create_error_tool_result(f"Tool {tool_call['name']} not found"),
            "isError": True,
        }

    try:
        prepared_call = _prepare_tool_call_arguments(tool, tool_call)
        validated_args = validate_tool_arguments(
            tool.parameters, prepared_call.get("arguments") or {}
        )
        if config.beforeToolCall:
            before_result = await _maybe_await(
                config.beforeToolCall(
                    {
                        "assistantMessage": assistant_message,
                        "toolCall": tool_call,
                        "args": validated_args,
                        "context": current_context,
                    },
                    signal,
                )
            )
            if _is_aborted(signal):
                return {
                    "kind": "immediate",
                    "result": _create_error_tool_result("Operation aborted"),
                    "isError": True,
                }
            if before_result and before_result.get("block"):
                return {
                    "kind": "immediate",
                    "result": _create_error_tool_result(
                        before_result.get("reason") or "Tool execution was blocked"
                    ),
                    "isError": True,
                }
        if _is_aborted(signal):
            return {
                "kind": "immediate",
                "result": _create_error_tool_result("Operation aborted"),
                "isError": True,
            }
        return {
            "kind": "prepared",
            "toolCall": tool_call,
            "tool": tool,
            "args": validated_args,
        }
    except Exception as error:  # noqa: BLE001 — match upstream catch-all
        return {
            "kind": "immediate",
            "result": _create_error_tool_result(str(error)),
            "isError": True,
        }


async def _execute_prepared_tool_call(
    prepared: _PreparedToolCall,
    signal: Any | None,
    emit: AgentEventSink,
) -> _ExecutedToolCallOutcome:
    update_events: list[asyncio.Task[None] | Awaitable[None]] = []
    accepting_updates = True

    def on_update(partial_result: AgentToolResult) -> None:
        nonlocal accepting_updates
        if not accepting_updates:
            return

        async def _do() -> None:
            await _emit(
                emit,
                {
                    "type": "tool_execution_update",
                    "toolCallId": prepared["toolCall"]["id"],
                    "toolName": prepared["toolCall"]["name"],
                    "args": prepared["toolCall"].get("arguments"),
                    "partialResult": partial_result,
                },
            )

        update_events.append(asyncio.create_task(_do()))

    try:
        result = await prepared["tool"].execute(
            prepared["toolCall"]["id"],
            prepared["args"],
            signal,
            on_update,
        )
        accepting_updates = False
        if update_events:
            await asyncio.gather(*update_events)
        return {"result": result, "isError": False}
    except Exception as error:  # noqa: BLE001
        accepting_updates = False
        if update_events:
            await asyncio.gather(*update_events)
        return {
            "result": _create_error_tool_result(str(error)),
            "isError": True,
        }
    finally:
        accepting_updates = False


async def _finalize_executed_tool_call(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    prepared: _PreparedToolCall,
    executed: _ExecutedToolCallOutcome,
    config: AgentLoopConfig,
    signal: Any | None,
) -> _FinalizedToolCallOutcome:
    result = executed["result"]
    is_error = executed["isError"]

    if config.afterToolCall:
        try:
            after_result = await _maybe_await(
                config.afterToolCall(
                    {
                        "assistantMessage": assistant_message,
                        "toolCall": prepared["toolCall"],
                        "args": prepared["args"],
                        "result": result,
                        "isError": is_error,
                        "context": current_context,
                    },
                    signal,
                )
            )
            if after_result:
                merged = dict(result)
                if "content" in after_result:
                    merged["content"] = after_result["content"]
                if "details" in after_result:
                    merged["details"] = after_result["details"]
                if "usage" in after_result:
                    merged["usage"] = after_result["usage"]
                if "terminate" in after_result:
                    merged["terminate"] = after_result["terminate"]
                result = cast(AgentToolResult, merged)
                if "isError" in after_result:
                    is_error = bool(after_result["isError"])
        except Exception as error:  # noqa: BLE001
            result = _create_error_tool_result(str(error))
            is_error = True

    return {
        "toolCall": prepared["toolCall"],
        "result": result,
        "isError": is_error,
    }


def _create_error_tool_result(message: str) -> AgentToolResult:
    return {
        "content": [{"type": "text", "text": message}],
        "details": {},
    }


async def _emit_tool_execution_end(
    finalized: _FinalizedToolCallOutcome, emit: AgentEventSink
) -> None:
    await _emit(
        emit,
        {
            "type": "tool_execution_end",
            "toolCallId": finalized["toolCall"]["id"],
            "toolName": finalized["toolCall"]["name"],
            "result": finalized["result"],
            "isError": finalized["isError"],
        },
    )


def _create_tool_result_message(finalized: _FinalizedToolCallOutcome) -> ToolResultMessage:
    result = finalized["result"]
    msg: ToolResultMessage = {
        "role": "toolResult",
        "toolCallId": finalized["toolCall"]["id"],
        "toolName": finalized["toolCall"]["name"],
        "content": result.get("content") or [],
        "isError": finalized["isError"],
        "timestamp": int(time.time() * 1000),
    }
    if "details" in result:
        msg["details"] = result["details"]
    if "usage" in result:
        msg["usage"] = result["usage"]  # type: ignore[typeddict-item]
    added = result.get("addedToolNames")
    if added:
        msg["addedToolNames"] = list(added)
    return msg


async def _emit_tool_result_message(
    tool_result_message: ToolResultMessage, emit: AgentEventSink
) -> None:
    await _emit(emit, {"type": "message_start", "message": tool_result_message})
    await _emit(emit, {"type": "message_end", "message": tool_result_message})
