"""Async event stream — port of utils/event-stream.ts."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Generic, TypeVar

from ..types import AssistantMessage, AssistantMessageEvent

T = TypeVar("T")
R = TypeVar("R")


class EventStream(Generic[T, R]):
    def __init__(
        self,
        is_complete: Callable[[T], bool],
        extract_result: Callable[[T], R],
    ) -> None:
        self._queue: list[T] = []
        self._waiting: list[asyncio.Future[tuple[T | None, bool]]] = []
        self._done = False
        self._is_complete = is_complete
        self._extract_result = extract_result
        self._final_result: asyncio.Future[R] = asyncio.get_event_loop().create_future()
        # Prefer get_running_loop when available
        try:
            loop = asyncio.get_running_loop()
            self._final_result = loop.create_future()
        except RuntimeError:
            pass

    def push(self, event: T) -> None:
        if self._done:
            return
        if self._is_complete(event):
            self._done = True
            if not self._final_result.done():
                self._final_result.set_result(self._extract_result(event))
        if self._waiting:
            fut = self._waiting.pop(0)
            if not fut.done():
                fut.set_result((event, False))
        else:
            self._queue.append(event)

    def end(self, result: R | None = None) -> None:
        self._done = True
        if result is not None and not self._final_result.done():
            self._final_result.set_result(result)
        while self._waiting:
            fut = self._waiting.pop(0)
            if not fut.done():
                fut.set_result((None, True))

    def __aiter__(self) -> AsyncIterator[T]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[T]:
        while True:
            if self._queue:
                yield self._queue.pop(0)
            elif self._done:
                return
            else:
                loop = asyncio.get_running_loop()
                fut: asyncio.Future[tuple[T | None, bool]] = loop.create_future()
                self._waiting.append(fut)
                value, done = await fut
                if done:
                    return
                assert value is not None
                yield value

    def result(self) -> asyncio.Future[R] | asyncio.Task[R]:
        return self._final_result

    async def await_result(self) -> R:
        return await self._final_result


class AssistantMessageEventStream(EventStream[AssistantMessageEvent, AssistantMessage]):
    def __init__(self) -> None:
        def is_complete(event: AssistantMessageEvent) -> bool:
            return event["type"] in ("done", "error")

        def extract(event: AssistantMessageEvent) -> AssistantMessage:
            if event["type"] == "done":
                return event["message"]  # type: ignore[return-value]
            if event["type"] == "error":
                return event["error"]  # type: ignore[return-value]
            raise RuntimeError("Unexpected event type for final result")

        super().__init__(is_complete, extract)

    async def result(self) -> AssistantMessage:  # type: ignore[override]
        return await self.await_result()


def create_assistant_message_event_stream() -> AssistantMessageEventStream:
    return AssistantMessageEventStream()
