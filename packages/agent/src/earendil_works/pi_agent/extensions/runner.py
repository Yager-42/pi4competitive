"""Extension lifecycle dispatch.

upstream: packages/coding-agent/src/core/extensions/runner.ts
"""
from __future__ import annotations

import copy
import inspect
from collections.abc import Callable
from typing import Any

from .types import Extension, ExtensionError, ExtensionRuntime, LoadExtensionsResult, RegisteredTool


async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class _Context:
    def __init__(self, runner: "ExtensionRunner", system_prompt: str | None = None) -> None:
        self._runner = runner
        self._system_prompt = system_prompt

    def _get(self, name: str) -> Callable[..., Any]:
        self._runner._assert_active()
        try:
            return self._runner._context_actions[name]
        except KeyError as exc:
            raise RuntimeError(f"Extension context action not bound: {name}") from exc

    @property
    def cwd(self) -> str:
        self._runner._assert_active()
        return self._runner.cwd

    @property
    def sessionManager(self) -> Any:
        return self._get("getSessionManager")()

    @property
    def modelRegistry(self) -> Any:
        return self._get("getModelRegistry")()

    @property
    def model(self) -> Any:
        return self._get("getModel")()

    @property
    def signal(self) -> Any:
        return self._get("getSignal")()

    def abort(self) -> None:
        self._get("abort")()

    def isIdle(self) -> bool:
        return bool(self._get("isIdle")())

    def hasPendingMessages(self) -> bool:
        return bool(self._get("hasPendingMessages")())

    def shutdown(self) -> None:
        self._get("shutdown")()

    def getContextUsage(self) -> dict[str, Any] | None:
        return self._get("getContextUsage")()

    def compact(self, options: dict[str, Any] | None = None) -> Any:
        return self._get("compact")(options)

    def getSystemPrompt(self) -> str:
        if self._system_prompt is not None:
            return self._system_prompt
        return str(self._get("getSystemPrompt")())


class ExtensionRunner:
    def __init__(self, extensions: list[Extension], runtime: ExtensionRuntime, cwd: str | Any) -> None:
        self.extensions = extensions
        self.runtime = runtime
        self.cwd = str(cwd)
        self._context_actions: dict[str, Callable[..., Any]] = {}
        self._error_listeners: set[Callable[[ExtensionError], None]] = set()
        self._stale_message: str | None = None

    @classmethod
    def from_load_result(cls, result: LoadExtensionsResult, cwd: str | Any) -> "ExtensionRunner":
        return cls(result.extensions, result.runtime, cwd)

    def bind_core(
        self,
        actions: dict[str, Callable[..., Any]] | None = None,
        context_actions: dict[str, Callable[..., Any]] | None = None,
    ) -> None:
        self.runtime.actions.update(actions or {})
        self._context_actions.update(context_actions or {})

    def invalidate(self, message: str | None = None) -> None:
        self._stale_message = self._stale_message or message or "This extension context is stale"
        self.runtime.invalidate(self._stale_message)

    def _assert_active(self) -> None:
        if self._stale_message:
            raise RuntimeError(self._stale_message)
        self.runtime.assert_active()

    def create_context(self, system_prompt: str | None = None) -> _Context:
        self._assert_active()
        return _Context(self, system_prompt)

    def on_error(self, listener: Callable[[ExtensionError], None]) -> Callable[[], None]:
        self._error_listeners.add(listener)
        return lambda: self._error_listeners.discard(listener)

    def emit_error(self, error: ExtensionError) -> None:
        for listener in tuple(self._error_listeners):
            try:
                listener(error)
            except Exception:  # noqa: BLE001 — error reporting must not break dispatch
                continue

    def has_handlers(self, event: str) -> bool:
        return any(extension.handlers.get(event) for extension in self.extensions)

    def get_all_registered_tools(self) -> list[RegisteredTool]:
        tools: dict[str, RegisteredTool] = {}
        for extension in self.extensions:
            for name, tool in extension.tools.items():
                tools.setdefault(name, tool)
        return list(tools.values())

    async def _handlers(self, event: dict[str, Any], ctx: _Context | None = None):
        context = ctx or self.create_context()
        for extension in self.extensions:
            for handler in extension.handlers.get(str(event["type"]), []):
                yield extension, handler, context

    async def emit(self, event: dict[str, Any]) -> dict[str, Any] | None:
        result = None
        plans = 0
        legacy = False
        async for extension, handler, ctx in self._handlers(event):
            try:
                value = await _await(handler(event, ctx))
                if event["type"] == "session_before_compact" and value:
                    if value.get("cancel"):
                        return value
                    plans += int(value.get("compactionPlan") is not None)
                    legacy = legacy or value.get("compaction") is not None
                    if plans > 1 or (plans and legacy):
                        message = "session_before_compact compaction plan collision"
                        self.emit_error(ExtensionError(extension.path, str(event["type"]), message))
                        return {"compactionCollision": True}
                    result = value if value.get("compactionPlan") is not None else value or result
            except Exception as exc:  # noqa: BLE001
                self.emit_error(ExtensionError(extension.path, str(event["type"]), str(exc)))
        return result

    async def emit_context(self, messages: list[Any]) -> list[Any]:
        current = copy.deepcopy(messages)
        event = {"type": "context", "messages": current}
        async for extension, handler, ctx in self._handlers(event):
            try:
                value = await _await(handler(event, ctx))
                if value and value.get("messages") is not None:
                    current = value["messages"]
                    event = {"type": "context", "messages": current}
            except Exception as exc:  # noqa: BLE001
                self.emit_error(ExtensionError(extension.path, "context", str(exc)))
        return current

    async def emit_before_provider_request(self, payload: Any) -> Any:
        current = payload
        event = {"type": "before_provider_request", "payload": current}
        async for extension, handler, ctx in self._handlers(event):
            try:
                value = await _await(handler(event, ctx))
                if value is not None:
                    current = value
                    event = {"type": "before_provider_request", "payload": current}
            except Exception as exc:  # noqa: BLE001
                self.emit_error(ExtensionError(extension.path, "before_provider_request", str(exc)))
        return current

    async def emit_before_provider_headers(self, headers: dict[str, str | None]) -> dict[str, str | None]:
        await self.emit({"type": "before_provider_headers", "headers": headers})
        return headers

    async def emit_before_agent_start(
        self, prompt: str, images: list[Any] | None, system_prompt: str, system_prompt_options: dict[str, Any]
    ) -> dict[str, Any] | None:
        current = system_prompt
        messages: list[Any] = []
        modified = False
        event = {"type": "before_agent_start", "prompt": prompt, "images": images,
                 "systemPrompt": current, "systemPromptOptions": system_prompt_options}
        async for extension, handler, _ in self._handlers(event, self.create_context(current)):
            try:
                value = await _await(handler(event, self.create_context(current)))
                if not value:
                    continue
                if value.get("message") is not None:
                    messages.append(value["message"])
                if "systemPrompt" in value:
                    current = value["systemPrompt"]
                    modified = True
                    event["systemPrompt"] = current
            except Exception as exc:  # noqa: BLE001
                self.emit_error(ExtensionError(extension.path, "before_agent_start", str(exc)))
        return ({"messages": messages or None, "systemPrompt": current if modified else None}
                if messages or modified else None)

    async def emit_tool_call(self, event: dict[str, Any]) -> dict[str, Any] | None:
        result = None
        async for extension, handler, ctx in self._handlers(event):
            try:
                value = await _await(handler(event, ctx))
                if value:
                    result = value
                    if value.get("block"):
                        return value
            except Exception as exc:  # noqa: BLE001
                self.emit_error(ExtensionError(extension.path, "tool_call", str(exc)))
        return result

    async def emit_tool_result(self, event: dict[str, Any]) -> dict[str, Any] | None:
        changed = False
        current = dict(event)
        async for extension, handler, ctx in self._handlers(current):
            try:
                value = await _await(handler(current, ctx))
                if value:
                    for key in ("content", "details", "isError", "usage"):
                        if key in value:
                            current[key] = value[key]
                            changed = True
            except Exception as exc:  # noqa: BLE001
                self.emit_error(ExtensionError(extension.path, "tool_result", str(exc)))
        return ({key: current.get(key) for key in ("content", "details", "isError", "usage")}
                if changed else None)

    async def emit_message_end(self, event: dict[str, Any]) -> Any | None:
        current = event["message"]
        changed = False
        async for extension, handler, ctx in self._handlers(event):
            try:
                value = await _await(handler({**event, "message": current}, ctx))
                replacement = value.get("message") if value else None
                if replacement is None:
                    continue
                if replacement.get("role") != current.get("role"):
                    self.emit_error(ExtensionError(extension.path, "message_end",
                                                   "message_end handlers must return a message with the same role"))
                    continue
                current = replacement
                changed = True
            except Exception as exc:  # noqa: BLE001
                self.emit_error(ExtensionError(extension.path, "message_end", str(exc)))
        return current if changed else None


__all__ = ["ExtensionRunner"]
