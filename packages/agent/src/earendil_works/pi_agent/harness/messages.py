"""Harness message helpers.

upstream: packages/agent/src/harness/messages.ts
"""
from __future__ import annotations

from typing import Any

from earendil_works.pi_ai.types import ImageContent, Message, TextContent
from earendil_works.pi_agent.types import AgentMessage

COMPACTION_SUMMARY_PREFIX = (
    "The conversation history before this point was compacted into the following summary:\n\n<summary>\n"
)
COMPACTION_SUMMARY_SUFFIX = "\n</summary>"

BRANCH_SUMMARY_PREFIX = (
    "The following is a summary of a branch that this conversation came back from:\n\n<summary>\n"
)
BRANCH_SUMMARY_SUFFIX = "</summary>"


def create_branch_summary_message(summary: str, from_id: str, timestamp: str) -> dict[str, Any]:
    from datetime import datetime

    try:
        ts = int(datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        ts = 0
    return {
        "role": "branchSummary",
        "summary": summary,
        "fromId": from_id,
        "timestamp": ts,
    }


def create_compaction_summary_message(
    summary: str, tokens_before: int, timestamp: str
) -> dict[str, Any]:
    from datetime import datetime

    try:
        ts = int(datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        ts = 0
    return {
        "role": "compactionSummary",
        "summary": summary,
        "tokensBefore": tokens_before,
        "timestamp": ts,
    }


def create_custom_message(
    custom_type: str,
    content: str | list[TextContent | ImageContent],
    display: bool,
    details: Any,
    timestamp: str,
) -> dict[str, Any]:
    from datetime import datetime

    try:
        ts = int(datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        ts = 0
    return {
        "role": "custom",
        "customType": custom_type,
        "content": content,
        "display": display,
        "details": details,
        "timestamp": ts,
    }


def convert_to_llm(messages: list[AgentMessage]) -> list[Message]:
    out: list[Message] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role == "branchSummary":
            text = BRANCH_SUMMARY_PREFIX + str(m.get("summary", "")) + BRANCH_SUMMARY_SUFFIX
            out.append(
                {
                    "role": "user",
                    "content": [{"type": "text", "text": text}],
                    "timestamp": int(m.get("timestamp") or 0),
                }
            )
        elif role == "compactionSummary":
            text = COMPACTION_SUMMARY_PREFIX + str(m.get("summary", "")) + COMPACTION_SUMMARY_SUFFIX
            out.append(
                {
                    "role": "user",
                    "content": [{"type": "text", "text": text}],
                    "timestamp": int(m.get("timestamp") or 0),
                }
            )
        elif role == "custom":
            # ``display`` controls whether this persisted message is sent to
            # the model; hidden custom entries remain UI/session metadata.
            if not bool(m.get("display")):
                continue
            content = m.get("content")
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            out.append(
                {
                    "role": "user",
                    "content": content,  # type: ignore[typeddict-item]
                    "timestamp": int(m.get("timestamp") or 0),
                }
            )
        elif role in ("user", "assistant", "toolResult"):
            out.append(m)  # type: ignore[arg-type]
    return out


__all__ = [
    "BRANCH_SUMMARY_PREFIX",
    "BRANCH_SUMMARY_SUFFIX",
    "COMPACTION_SUMMARY_PREFIX",
    "COMPACTION_SUMMARY_SUFFIX",
    "convert_to_llm",
    "create_branch_summary_message",
    "create_compaction_summary_message",
    "create_custom_message",
]
