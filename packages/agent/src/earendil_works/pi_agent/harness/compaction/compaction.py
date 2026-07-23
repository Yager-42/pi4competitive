"""should_compact / compact / prepare_compaction (core).

upstream: packages/agent/src/harness/compaction/compaction.ts
"""
from __future__ import annotations

from typing import Any

from earendil_works.pi_agent.types import AgentMessage

DEFAULT_COMPACTION_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "reserveTokens": 16384,
    "keepRecentTokens": 20000,
}


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) for thresholds."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def estimate_context_tokens(messages: list[AgentMessage]) -> int:
    total = 0
    for m in messages:
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    total += estimate_tokens(str(block.get("text") or ""))
                elif isinstance(block, dict) and block.get("type") == "toolCall":
                    total += estimate_tokens(str(block.get("name") or ""))
                    total += estimate_tokens(str(block.get("arguments") or ""))
    return total


def calculate_context_tokens(messages: list[AgentMessage]) -> int:
    return estimate_context_tokens(messages)


def get_last_assistant_usage(messages: list[AgentMessage]) -> dict[str, Any] | None:
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "assistant":
            usage = m.get("usage")
            if isinstance(usage, dict):
                return usage
    return None


def should_compact(
    messages: list[AgentMessage],
    context_window: int,
    settings: dict[str, Any] | None = None,
) -> bool:
    settings = {**DEFAULT_COMPACTION_SETTINGS, **(settings or {})}
    if not settings.get("enabled", True):
        return False
    reserve = int(settings.get("reserveTokens") or 0)
    used = estimate_context_tokens(messages)
    return used >= max(0, context_window - reserve)


def find_turn_start_index(messages: list[AgentMessage], from_index: int | None = None) -> int:
    end = len(messages) if from_index is None else min(from_index, len(messages))
    for i in range(end - 1, -1, -1):
        m = messages[i]
        if isinstance(m, dict) and m.get("role") == "user":
            return i
    return 0


def find_cut_point(
    messages: list[AgentMessage],
    keep_recent_tokens: int = 20000,
) -> int:
    """Return index to cut before; keep recent messages approximating keep_recent_tokens."""
    if not messages:
        return 0
    budget = 0
    for i in range(len(messages) - 1, -1, -1):
        budget += estimate_context_tokens([messages[i]])
        if budget >= keep_recent_tokens:
            # cut before this message's turn start
            return find_turn_start_index(messages, i)
    return 0


def serialize_conversation(messages: list[AgentMessage]) -> str:
    parts: list[str] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role", "?")
        content = m.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            texts = []
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text":
                    texts.append(str(b.get("text") or ""))
            text = "\n".join(texts)
        else:
            text = str(content)
        parts.append(f"{role}: {text}")
    return "\n".join(parts)


async def generate_summary(
    messages: list[AgentMessage],
    stream_fn: Any = None,
    model: Any = None,
) -> str:
    """Fallback summary without LLM when stream_fn/model missing."""
    serialized = serialize_conversation(messages)
    if len(serialized) <= 500:
        return serialized
    return serialized[:500] + "\n…"


async def generate_summary_with_usage(
    messages: list[AgentMessage],
    stream_fn: Any = None,
    model: Any = None,
) -> dict[str, Any]:
    summary = await generate_summary(messages, stream_fn, model)
    return {"summary": summary, "usage": None}


def prepare_compaction(
    messages: list[AgentMessage],
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = {**DEFAULT_COMPACTION_SETTINGS, **(settings or {})}
    cut = find_cut_point(messages, int(settings.get("keepRecentTokens") or 20000))
    return {
        "cutIndex": cut,
        "messagesToSummarize": list(messages[:cut]),
        "messagesToKeep": list(messages[cut:]),
    }


async def compact(
    messages: list[AgentMessage],
    settings: dict[str, Any] | None = None,
    stream_fn: Any = None,
    model: Any = None,
) -> dict[str, Any]:
    prep = prepare_compaction(messages, settings)
    summary = await generate_summary(prep["messagesToSummarize"], stream_fn, model)
    return {
        "summary": summary,
        "cutIndex": prep["cutIndex"],
        "keptMessages": prep["messagesToKeep"],
        "tokensBefore": estimate_context_tokens(messages),
    }


__all__ = [
    "DEFAULT_COMPACTION_SETTINGS",
    "calculate_context_tokens",
    "compact",
    "estimate_context_tokens",
    "estimate_tokens",
    "find_cut_point",
    "find_turn_start_index",
    "generate_summary",
    "generate_summary_with_usage",
    "get_last_assistant_usage",
    "prepare_compaction",
    "serialize_conversation",
    "should_compact",
]
