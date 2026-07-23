"""Branch summarization helpers.

upstream: packages/agent/src/harness/compaction/branch-summarization.ts
"""
from __future__ import annotations

from typing import Any

from earendil_works.pi_agent.harness.types import SessionTreeEntry
from .compaction import generate_summary, serialize_conversation


def collect_entries_for_branch_summary(
    entries: list[SessionTreeEntry],
) -> dict[str, Any]:
    message_entries = [e for e in entries if e.get("type") == "message"]
    return {
        "entries": message_entries,
        "count": len(message_entries),
    }


async def generate_branch_summary(
    entries: list[SessionTreeEntry],
    stream_fn: Any = None,
    model: Any = None,
) -> str:
    collected = collect_entries_for_branch_summary(entries)
    messages = [e["message"] for e in collected["entries"] if "message" in e]  # type: ignore[index]
    if not messages:
        return ""
    return await generate_summary(messages, stream_fn, model)  # type: ignore[arg-type]


def prepare_branch_entries(
    path_entries: list[SessionTreeEntry],
    from_id: str | None,
) -> list[SessionTreeEntry]:
    if not from_id:
        return list(path_entries)
    out: list[SessionTreeEntry] = []
    for e in path_entries:
        out.append(e)
        if e.get("id") == from_id:
            break
    return out


__all__ = [
    "collect_entries_for_branch_summary",
    "generate_branch_summary",
    "prepare_branch_entries",
    "serialize_conversation",
]
