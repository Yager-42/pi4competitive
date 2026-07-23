"""Default stream function injection.

upstream: packages/agent/src/stream-fn.ts
"""
from __future__ import annotations

from earendil_works.pi_agent.types import StreamFn

_default_stream_fn: StreamFn | None = None


def set_default_stream_fn(fn: StreamFn | None) -> None:
    """Set process-wide default StreamFn used when Agent/loop omit an explicit one."""
    global _default_stream_fn
    _default_stream_fn = fn


def get_default_stream_fn() -> StreamFn | None:
    return _default_stream_fn


__all__ = ["get_default_stream_fn", "set_default_stream_fn"]
