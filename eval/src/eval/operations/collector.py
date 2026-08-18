"""operations_collector (D11 §12.5).

读 data/runs/<task_id>/events.jsonl (RunJournal) + task projection + SOCM,
产 operations.json: search/fetch 数, tool 调用成功率, fallback 次数,
terminal status, token/cost, 耗时, coverage cells, distinct domains,
evidence count, 失败阶段.

事件源统一为 RunJournal schema（``{event_id, run_id, event_type, payload,
created_at}``）：A2 由 competitive_app 的 RunJournal 写，A1 由 eval 本地
RunJournal 写（见 eval.runner.run_journal）。payload key 兼容两种写法：
``tool_name``（journal_bridge 用）与 ``name``（早期测试用）。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass
class OperationsResult:
    terminal_status: str = "unknown"
    failure_stage: str | None = None
    search_calls: int = 0
    fetch_calls: int = 0
    other_tool_calls: int = 0
    tool_calls_total: int = 0
    tool_calls_ok: int = 0
    tool_calls_error: int = 0
    tool_success_rate: float = 0.0
    fallback_count: int = 0
    distinct_domains: int = 0
    evidence_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    run_started_at: str = ""
    run_finished_at: str = ""
    duration_seconds: float = 0.0
    coverage_filled: int = 0
    coverage_unknown: int = 0
    coverage_conflict: int = 0
    coverage_total: int = 0
    coverage_ratio: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SEARCH_TOOL_NAMES = {"tavily_search", "anysearch_search", "grok_search"}
_FETCH_TOOL_NAMES = {"tavily_fetch", "anysearch_fetch", "grok_fetch"}
_FALLBACK_EVENT_TYPES = ("llm.fallback_switch", "llm.fallback_start")


def extract_urls_from_details(details: Any) -> list[str]:
    """search_result.v1 / fetch_result.v1 ``details`` → 来源 URL 列表。

    A1 tool 包装器与 A2 journal_bridge 都把该结构放进 ``tool.finished``
    payload，collector 与 A1 共用本 helper。
    """
    if not isinstance(details, dict):
        return []
    urls: list[str] = []
    hits = details.get("hits")
    if isinstance(hits, list):
        for hit in hits:
            if isinstance(hit, dict) and isinstance(hit.get("url"), str) and hit["url"]:
                urls.append(hit["url"])
    url = details.get("url")
    if isinstance(url, str) and url:
        urls.append(url)
    return urls


def _tool_name(payload: dict[str, Any]) -> str:
    return str(payload.get("tool_name") or payload.get("name") or "")


def _collect_urls(payload: dict[str, Any]) -> list[str]:
    """tool.finished payload → 来源 URL 列表（urls 数组 > 单 url/source > details）。"""
    urls: list[str] = []
    arr = payload.get("urls")
    if isinstance(arr, list):
        for u in arr:
            if isinstance(u, str) and u:
                urls.append(u)
    if not urls:
        single = payload.get("url") or payload.get("source")
        if isinstance(single, str) and single:
            urls.append(single)
    if not urls:
        urls = extract_urls_from_details(payload.get("details"))
    return urls


def _usage_tokens(usage: Any) -> tuple[int, int, int]:
    """usage dict（pi 语义：input/output/cacheRead/cacheWrite/cost.total）→ tokens。"""
    if not isinstance(usage, dict):
        return 0, 0, 0
    try:
        inp = int(usage.get("input") or 0)
        out = int(usage.get("output") or 0)
        cache_read = int(usage.get("cacheRead") or 0)
        cache_write = int(usage.get("cacheWrite") or 0)
    except (TypeError, ValueError):
        return 0, 0, 0
    return inp + cache_read, out + cache_write, inp + cache_read + out + cache_write


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def collect_operations(
    *,
    events_path: Path | str,
    projection: dict[str, Any],
    socm: dict[str, Any] | None,
) -> OperationsResult:
    result = OperationsResult()
    result.terminal_status = projection.get("status", "unknown")
    result.failure_stage = projection.get("first_non_ok_stage")
    domains: set[str] = set()
    evidence_urls: set[str] = set()
    started_at: datetime | None = None
    finished_at: datetime | None = None
    started_at_raw = ""
    finished_at_raw = ""

    p = Path(events_path)
    # v0.2.10 duration fix: A2 journals can accumulate late harness events
    # (agent.started/llm.* from later tasks), inflating the raw min/max span.
    # Prefer the task stage window (task.stage_start plan → last task.stage_end);
    # fall back to agent.started/agent.finished (A1 has no stage events).
    stage_start_ts: datetime | None = None
    stage_start_raw = ""
    stage_end_ts: datetime | None = None
    stage_end_raw = ""
    agent_start_ts: datetime | None = None
    agent_start_raw = ""
    agent_end_ts: datetime | None = None
    agent_end_raw = ""
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            et = evt.get("event_type", "")
            payload = evt.get("payload") or {}
            created = evt.get("created_at")
            ts = _parse_timestamp(created)
            if ts is not None:
                if started_at is None or ts < started_at:
                    started_at = ts
                    started_at_raw = str(created)
                if finished_at is None or ts > finished_at:
                    finished_at = ts
                    finished_at_raw = str(created)
                if (
                    et == "task.stage_start"
                    and payload.get("stage") == "plan"
                    and stage_start_ts is None
                ):
                    stage_start_ts = ts
                    stage_start_raw = str(created)
                elif et == "task.stage_end":
                    if stage_end_ts is None or ts > stage_end_ts:
                        stage_end_ts = ts
                        stage_end_raw = str(created)
                elif et == "agent.started":
                    if agent_start_ts is None:
                        agent_start_ts = ts
                        agent_start_raw = str(created)
                elif et == "agent.finished":
                    if agent_end_ts is None or ts > agent_end_ts:
                        agent_end_ts = ts
                        agent_end_raw = str(created)
            if et == "tool.called":
                name = _tool_name(payload)
                if name in _SEARCH_TOOL_NAMES:
                    result.search_calls += 1
                elif name in _FETCH_TOOL_NAMES:
                    result.fetch_calls += 1
                elif name:
                    result.other_tool_calls += 1
            elif et == "tool.finished":
                name = _tool_name(payload)
                result.tool_calls_total += 1
                # 缺失 status（旧 journal）→ 默认 ok；其余非 "ok" 一律算 error
                # （含 "error"、"budget_exhausted" —— A1 对超额调用发 status=error）
                if payload.get("status") in (None, "ok"):
                    result.tool_calls_ok += 1
                else:
                    result.tool_calls_error += 1
                for url in _collect_urls(payload):
                    try:
                        domains.add(urlparse(url).netloc)
                        evidence_urls.add(url)
                    except (ValueError, TypeError):
                        pass
            elif et in _FALLBACK_EVENT_TYPES:
                result.fallback_count += 1
            elif et == "llm.response":
                inp, outp, total = _usage_tokens(payload.get("usage"))
                result.prompt_tokens += inp
                result.completion_tokens += outp
                result.total_tokens += total
                usage = payload.get("usage")
                if isinstance(usage, dict):
                    cost = usage.get("cost")
                    if isinstance(cost, dict):
                        total_cost = cost.get("total")
                        if isinstance(total_cost, (int, float)) and not isinstance(total_cost, bool):
                            result.cost += float(total_cost)

    result.distinct_domains = len(domains)
    if result.tool_calls_total > 0:
        result.tool_success_rate = result.tool_calls_ok / result.tool_calls_total
    if stage_start_ts is not None and stage_end_ts is not None:
        # A2: stage window (plan → write end) — immune to late-task contamination.
        result.run_started_at = stage_start_raw
        result.run_finished_at = stage_end_raw
        result.duration_seconds = round((stage_end_ts - stage_start_ts).total_seconds(), 3)
    elif agent_start_ts is not None and agent_end_ts is not None:
        # A1: no stage events; agent lifecycle window.
        result.run_started_at = agent_start_raw
        result.run_finished_at = agent_end_raw
        result.duration_seconds = round((agent_end_ts - agent_start_ts).total_seconds(), 3)
    elif started_at is not None and finished_at is not None:
        # Fallback: raw min/max span.
        result.run_started_at = started_at_raw
        result.run_finished_at = finished_at_raw
        result.duration_seconds = round((finished_at - started_at).total_seconds(), 3)

    if socm:
        result.coverage_filled = int(socm.get("filled", 0))
        result.coverage_unknown = int(socm.get("unknown", 0))
        result.coverage_conflict = int(socm.get("conflict", 0))
        result.coverage_total = int(socm.get("total", 0))
        result.coverage_ratio = float(socm.get("ratio", 0.0))
    # evidence_count：projection 优先（A2 SOCM evidence），否则取 tool 事件里观测到的来源数。
    projected_evidence = int(projection.get("evidence_count", 0))
    result.evidence_count = projected_evidence if projected_evidence > 0 else len(evidence_urls)
    return result


__all__ = ["OperationsResult", "collect_operations", "extract_urls_from_details"]
