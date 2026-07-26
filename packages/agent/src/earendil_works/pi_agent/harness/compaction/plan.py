"""Provider-neutral CompactionPlan snapshot and validation."""
from __future__ import annotations

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


__all__ = ["snapshot_fingerprint", "validate_compaction_plan"]
