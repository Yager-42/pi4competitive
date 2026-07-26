"""Reasonix prefix-cache policy extension."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

_SUMMARY_INSTRUCTIONS = """Summarize with these headings:
Standing facts & constraints
Goal
Decisions & rationale
Important outcomes
Open questions & next step
Use concise bullets. Preserve identifiers, numbers, and user constraints. Do not guess."""


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _stable(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_stable(item) for item in value]
    return value


def _canonicalize(payload: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    tools = payload.get("tools")
    if tools is None:
        return payload, None
    if not isinstance(tools, list) or any(not isinstance(tool, dict) for tool in tools):
        return payload, "unsupported_tool_shape"
    candidate = copy.deepcopy(payload)
    tools = candidate["tools"]
    openai = all(isinstance(tool.get("function"), dict) and isinstance(tool["function"].get("name"), str)
                 for tool in tools)
    anthropic = all(isinstance(tool.get("name"), str) for tool in tools)
    if not (openai or anthropic):
        return payload, "unsupported_tool_shape"
    markers = [(index, tool.pop("cache_control")) for index, tool in enumerate(tools)
               if "cache_control" in tool]
    if len(markers) > 1 or (anthropic and markers and tools[markers[0][0]].get("defer_loading")):
        return payload, "unsupported_tool_cache_marker_shape"
    if openai:
        tools.sort(key=lambda tool: tool["function"]["name"])
        boundary = tools[-1] if tools else None
    else:
        immediate = sorted((tool for tool in tools if not tool.get("defer_loading")), key=lambda tool: tool["name"])
        deferred = sorted((tool for tool in tools if tool.get("defer_loading")), key=lambda tool: tool["name"])
        tools[:] = [*immediate, *deferred]
        boundary = immediate[-1] if immediate else None
    if markers and boundary is not None:
        boundary["cache_control"] = markers[0][1]
    candidate["tools"] = [_stable(tool) for tool in tools]
    return candidate, None


def _prefix_digest(payload: dict[str, Any]) -> str:
    prefix = {"system": payload.get("system") or payload.get("instructions"), "tools": payload.get("tools")}
    data = json.dumps(_stable(prefix), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode()).hexdigest()


@dataclass
class _State:
    epoch: int = 0
    baseline: str | None = None
    expected_cold: bool = False
    diagnostics: list[str] = field(default_factory=list)
    buckets: dict[int, dict[str, int]] = field(default_factory=dict)
    pending_auto: bool = False
    consecutive_rewrites: int = 0
    auto_paused: bool = False


def register(api) -> None:
    state = _State()

    def before_request(event, _ctx):
        payload, diagnostic = _canonicalize(event["payload"])
        if diagnostic:
            state.diagnostics.append(diagnostic)
            return event["payload"]
        digest = _prefix_digest(payload)
        if state.baseline is None:
            state.baseline = digest
        elif digest != state.baseline:
            state.epoch += 1
            state.baseline = digest
            state.expected_cold = True
            state.diagnostics.append("prefix_break")
        else:
            state.expected_cold = False
        return payload

    def after_response(event, _ctx):
        status = event.get("status") or (event.get("response") or {}).get("status")
        if status is not None:
            state.diagnostics.append(f"provider_status:{status}")

    def message_end(event, _ctx):
        usage = (event.get("message") or {}).get("usage") or {}
        bucket = state.buckets.setdefault(state.epoch, {"cacheRead": 0, "cacheWrite": 0})
        bucket["cacheRead"] += int(usage.get("cacheRead") or 0)
        bucket["cacheWrite"] += int(usage.get("cacheWrite") or 0)

    def turn_end(_event, ctx):
        usage = ctx.getContextUsage() or {}
        tokens, window = usage.get("tokens"), usage.get("contextWindow")
        if not isinstance(tokens, (int, float)) or not isinstance(window, (int, float)) or window <= 0:
            state.diagnostics.append("context_usage_unavailable")
            return
        reserve = 16_384 if window >= 36_384 else min(16_384, math.ceil(window * 0.20))
        if tokens <= window - reserve:
            state.consecutive_rewrites = 0
            state.auto_paused = False
        elif not state.auto_paused:
            state.pending_auto = ctx.compact() == "accepted"

    def before_compact(event, _ctx):
        preparation = event.get("preparation") or {}
        entries = preparation.get("entries") or []
        if not entries:
            return None
        active = set(preparation.get("activeTurnEntryIds") or [])
        window = 0
        try:
            window = int((_ctx.getContextUsage() or {}).get("contextWindow") or 0)
        except RuntimeError:
            pass
        user_limit = min(1500, int(window * 0.15)) if window else 1500
        retain = []
        for entry in entries:
            message = entry["message"]
            small_user = message.get("role") == "user" and len(str(message.get("content") or "")) // 4 <= user_limit
            if entry["id"] in active or small_user:
                retain.append(entry["id"])
        fold = [entry["id"] for entry in entries if entry["id"] not in set(retain)]
        if not fold:
            return None
        return {"compactionPlan": {"version": 1,
                "snapshotFingerprint": preparation["snapshotFingerprint"],
                "foldEntryIds": fold, "retainEntryIds": retain,
                "summaryInstructions": _SUMMARY_INSTRUCTIONS,
                "details": {"policy": "prefix-cache", "epoch": state.epoch}}}

    def session_compact(_event, _ctx):
        state.epoch += 1
        state.baseline = None
        if state.pending_auto:
            state.consecutive_rewrites += 1
            state.auto_paused = state.consecutive_rewrites >= 2
            state.pending_auto = False

    api.on("before_provider_request", before_request)
    api.on("after_provider_response", after_response)
    api.on("message_end", message_end)
    api.on("turn_end", turn_end)
    api.on("session_before_compact", before_compact)
    api.on("session_compact", session_compact)


__all__ = ["register"]
