"""W1 HTTP client: drive competitive_app via POST /tasks (D4).

orchestrator 起独立 competitive_app 进程, 本 client 打 POST /tasks + poll
GET /tasks/{id} + GET /reports/{id}. 总 wall-clock guard 到 timeout abort.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class TaskResult:
    task_id: str
    terminal_status: str  # completed | failed | aborted | timeout
    report_markdown: str
    projection: dict[str, Any]
    trace: dict[str, Any]
    failure_stage: str | None = None


class CompetitiveAppClient:
    """HTTP client for competitive_app (A2 variant)."""

    def __init__(self, *, base_url: str = "http://127.0.0.1:8000", transport: Any = None):
        self._base_url = base_url.rstrip("/")
        self._transport = transport  # test injection

    async def run_task(
        self,
        *,
        research_brief: dict[str, Any],
        search_overrides: dict[str, Any] | None = None,
        timeout: float = 900.0,
        poll_interval: float = 5.0,
    ) -> TaskResult:
        body: dict[str, Any] = {"research_brief": research_brief}
        if search_overrides:
            body["search_overrides"] = search_overrides
        async with httpx.AsyncClient(
            base_url=self._base_url, transport=self._transport, timeout=30
        ) as client:
            resp = await client.post("/api/v2/tasks", json=body)
            resp.raise_for_status()
            task_id = resp.json()["task_id"]

            deadline = asyncio.get_event_loop().time() + timeout
            status = "running"
            projection: dict[str, Any] = {}
            while asyncio.get_event_loop().time() < deadline:
                t = await client.get(f"/api/v2/tasks/{task_id}")
                t.raise_for_status()
                td = t.json()
                status = td.get("status", "running")
                projection = td.get("projection") or {}
                if status in ("completed", "failed", "aborted"):
                    break
                await asyncio.sleep(poll_interval)

            if status not in ("completed", "failed", "aborted"):
                # timeout: abort
                try:
                    await client.post(f"/api/v2/tasks/{task_id}/abort")
                except httpx.HTTPError:
                    pass
                status = "aborted"

            # fetch report + trace
            report_md = ""
            try:
                r = await client.get(f"/api/v2/reports/{task_id}")
                if r.status_code == 200:
                    rd = r.json()
                    report_md = rd.get("markdown", "") if rd.get("ok") else ""
            except httpx.HTTPError:
                pass
            trace: dict[str, Any] = {}
            try:
                tr = await client.get(f"/api/v2/tasks/{task_id}/sessions")
                if tr.status_code == 200:
                    trace = tr.json()
            except httpx.HTTPError:
                pass

            failure_stage = (
                projection.get("first_non_ok_stage") if status != "completed" else None
            )
            return TaskResult(
                task_id=task_id,
                terminal_status=status,
                report_markdown=report_md,
                projection=projection,
                trace=trace,
                failure_stage=failure_stage,
            )


__all__ = ["CompetitiveAppClient", "TaskResult"]
