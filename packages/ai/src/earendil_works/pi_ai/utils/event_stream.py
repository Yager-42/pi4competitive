"""Async event stream — port of utils/event-stream.ts."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Generic, TypeVar

from ..types import AssistantMessage, AssistantMessageEvent

_log = logging.getLogger(__name__)


T = TypeVar("T")
R = TypeVar("R")
_MISSING = object()

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
        self._final_result: asyncio.Future[R] | None = None
        self._result_value: R | object = _MISSING
        self._result_error: BaseException | None = None
        self._pending_runner: Callable[[], Awaitable[None]] | None = None
        self._runner_task: asyncio.Task[None] | None = None
        self._started = False

    def _ensure_final_future(self) -> asyncio.Future[R]:
        if self._final_result is None:
            loop = asyncio.get_running_loop()
            self._final_result = loop.create_future()
            if self._result_error is not None:
                self._final_result.set_exception(self._result_error)
            elif self._result_value is not _MISSING:
                self._final_result.set_result(self._result_value)  # type: ignore[arg-type]
        return self._final_result

    async def _run_pending(self, runner: Callable[[], Awaitable[None]]) -> None:
        try:
            await runner()
        except asyncio.CancelledError as error:
            self.fail(error)
            raise
        except BaseException as error:
            if not self.fail(error):
                # The stream already completed (end()/push) and the failure
                # arrived during post-completion cleanup: the result stands,
                # but the producer failure must not disappear silently.
                _log.warning("event stream producer failed after completion: %r", error)
            if not isinstance(error, Exception):
                raise

    def _start_pending(self) -> None:
        if self._started or self._pending_runner is None or self._done:
            return
        loop = asyncio.get_running_loop()
        self._started = True
        runner = self._pending_runner
        self._pending_runner = None
        task = loop.create_task(self._run_pending(runner))
        self._runner_task = task

        def release(completed: asyncio.Task[None]) -> None:
            if self._runner_task is completed:
                self._runner_task = None
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(release)

    def start(self, runner: Callable[[], Awaitable[None]]) -> None:
        """Start a producer now, or defer it until this stream is consumed."""
        if self._started or self._done:
            return
        self._pending_runner = runner
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No running loop yet; ``__aiter__``/``await_result`` starts it.
            return
        self._start_pending()

    def _wake_waiters(self) -> None:
        while self._waiting:
            fut = self._waiting.pop(0)
            if not fut.done():
                fut.set_result((None, True))

    def fail(self, error: BaseException) -> bool:
        """Complete the stream with a producer failure and wake consumers.

        Returns True when the failure was applied, False when the stream had
        already completed (a late producer failure changes no result).
        """
        if self._done:
            return False
        self._done = True
        self._result_error = error
        if self._final_result is not None and not self._final_result.done():
            self._final_result.set_exception(error)
        self._wake_waiters()
        return True

    def push(self, event: T) -> None:
        if self._done:
            return
        if self._is_complete(event):
            self._done = True
            self._result_value = self._extract_result(event)
            if self._final_result is not None and not self._final_result.done():
                self._final_result.set_result(self._result_value)  # type: ignore[arg-type]
        if self._waiting:
            fut = self._waiting.pop(0)
            if not fut.done():
                fut.set_result((event, False))
        else:
            self._queue.append(event)

    def end(self, result: R | None = None) -> None:
        if self._done:
            return
        self._done = True
        if result is not None:
            self._result_value = result
            if self._final_result is not None and not self._final_result.done():
                self._final_result.set_result(result)
        else:
            self._result_error = RuntimeError("Event stream ended without a result")
            if self._final_result is not None and not self._final_result.done():
                self._final_result.set_exception(self._result_error)
        self._wake_waiters()

    def __aiter__(self) -> AsyncIterator[T]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[T]:
        self._start_pending()
        while True:
            if self._queue:
                yield self._queue.pop(0)
            elif self._done:
                return
            else:
                loop = asyncio.get_running_loop()
                fut: asyncio.Future[tuple[T | None, bool]] = loop.create_future()
                self._waiting.append(fut)
                try:
                    value, done = await fut
                finally:
                    if fut in self._waiting:
                        self._waiting.remove(fut)
                if done:
                    return
                assert value is not None
                yield value

    def result(self) -> asyncio.Future[R] | Awaitable[R]:
        """Return the result future, deferring loop-bound setup when necessary."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # A stream may be constructed synchronously and awaited in a later
            # loop. Creating a Future here would bind it to the wrong loop.
            return self.await_result()
        self._start_pending()
        return self._ensure_final_future()

    async def await_result(self) -> R:
        self._start_pending()
        return await self._ensure_final_future()


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
