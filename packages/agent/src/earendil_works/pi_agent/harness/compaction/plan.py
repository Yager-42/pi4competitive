"""Provider-neutral CompactionPlan snapshot and validation."""
from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any


def snapshot_fingerprint(entries: list[dict[str, Any]]) -> str:
    projection = [{"id": entry["id"], "message": entry.get("message")} for entry in entries]
    data = json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(data.encode()).hexdigest()


def validate_compaction_plan(
    plan: dict[str, Any], entries: list[dict[str, Any]], active_entry_ids: set[str] | None = None,
) -> None:
    ids = [entry["id"] for entry in entries]
    fold = plan.get("foldEntryIds") or []
    retain = plan.get("retainEntryIds") or []
    if plan.get("version") != 1 or plan.get("snapshotFingerprint") != snapshot_fingerprint(entries):
        raise ValueError("compaction plan snapshot mismatch")
    if len(fold) != len(set(fold)) or len(retain) != len(set(retain)) or set(fold) & set(retain):
        raise ValueError("compaction plan entries overlap or repeat")
    if set(fold) | set(retain) != set(ids):
        raise ValueError("compaction plan must partition every candidate")
    positions = {entry_id: index for index, entry_id in enumerate(ids)}
    if fold != sorted(fold, key=positions.__getitem__) or retain != sorted(retain, key=positions.__getitem__):
        raise ValueError("compaction plan entries must preserve snapshot order")
    if not (active_entry_ids or set()).issubset(retain):
        raise ValueError("compaction plan must retain the active turn")

    ownership = {entry_id: "fold" if entry_id in fold else "retain" for entry_id in ids}
    calls: dict[str, str] = {}
    for entry in entries:
        message = entry.get("message") or {}
        for block in message.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "toolCall":
                calls[str(block.get("id"))] = ownership[entry["id"]]
        if message.get("role") == "toolResult":
            call_id = str(message.get("toolCallId"))
            if call_id in calls and calls[call_id] != ownership[entry["id"]]:
                raise ValueError("tool call and result must remain atomic")


def mechanical_summary(messages: list[dict[str, Any]]) -> str:
    lines = [f"{message.get('role', '?')}: {message.get('content', '')}" for message in messages]
    return "\n".join(lines)[:2000] or "(empty conversation)"


async def isolated_summary(
    messages: list[dict[str, Any]], instructions: str, stream_fn: Any, model: Any,
    options: dict[str, Any] | None = None,
) -> str:
    if not stream_fn or not model:
        return mechanical_summary(messages)
    clean_options = {k: v for k, v in (options or {}).items()
                     if k not in ("sessionId", "onPayload", "onResponse")}
    context = {"systemPrompt": instructions, "messages": messages, "tools": []}
    for attempt in range(2):
        try:
            async def complete() -> Any:
                stream = stream_fn(model, context, clean_options)
                if hasattr(stream, "__await__"):
                    stream = await stream
                return await stream.result()

            result = await asyncio.wait_for(complete(), timeout=90)
            content = result.get("content") or []
            text = "\n".join(str(block.get("text") or "") for block in content
                             if isinstance(block, dict) and block.get("type") == "text")
            if text:
                return text
            raise RuntimeError("empty summary")
        except TimeoutError:
            break
        except Exception:  # noqa: BLE001
            if attempt:
                break
    return mechanical_summary(messages)


__all__ = ["isolated_summary", "mechanical_summary", "snapshot_fingerprint", "validate_compaction_plan"]
