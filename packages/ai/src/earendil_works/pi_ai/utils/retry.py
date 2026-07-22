"""Async retry helper."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 2,
    base_delay_ms: float = 200,
    max_delay_ms: float = 60_000,
) -> T:
    attempt = 0
    while True:
        try:
            return await fn()
        except Exception:
            if attempt >= max_retries:
                raise
            delay = min(max_delay_ms, base_delay_ms * (2**attempt)) / 1000.0
            await asyncio.sleep(delay)
            attempt += 1
