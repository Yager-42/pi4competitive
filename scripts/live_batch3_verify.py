"""Live verify: batch3 — clarify + evidences + dashboard + subscriptions (v0.3.3).

Real flow against live provider + search:
1. POST /tasks {query} -> awaiting_clarify + 3 questions
2. POST /tasks/{id}/clarify {answers} -> derive brief -> run -> completed
3. GET /evidences -> verify ACTIVE evidence indexed from SOCM
4. GET /dashboard -> verify aggregation (reports/evidence_total/token_total)
5. POST /subscriptions + POST /run -> verify subscription triggers a task
Saves artifacts to OUT.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path("/Users/huangyaokai/pi4competitive")
sys.path.insert(0, str(ROOT / "competitive_app/src"))
sys.path.insert(0, str(ROOT / "packages/ai/src"))
sys.path.insert(0, str(ROOT / "packages/agent/src"))

_QUOTES = "'\""  # strip both single and double quote chars from .env values
envp = ROOT / ".env"
if envp.is_file():
    for raw in envp.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip(_QUOTES))

QUERY = "Trae 这款 AI IDE 的竞品对比"
OUT = ROOT / "data/live_runs/batch3_verify"
OUT.mkdir(parents=True, exist_ok=True)
os.environ["SESSIONS_CWD"] = "live_batch3"
os.environ["SESSIONS_ROOT"] = str(ROOT / "data/sessions")
os.environ["APP_DB"] = str(OUT / "app.db")


async def _poll(c, tid, label, timeout=840):
    t0 = time.time()
    status = "pending"
    while time.time() - t0 < timeout:
        g = await c.get(f"/api/v2/tasks/{tid}")
        status = g.json().get("status")
        if status in {"completed", "failed", "aborted"}:
            break
        await asyncio.sleep(5)
    print(f"[{label}] status={status} elapsed={round(time.time()-t0,1)}s")
    return status


async def main() -> None:
    from httpx import ASGITransport, AsyncClient

    from competitive_app.adapter.in_.fastapi.app import create_app
    from competitive_app.wiring import build_application_state, load_config_from_env

    state = await build_application_state(load_config_from_env())
    app = create_app()
    app.state.application = state
    summary: dict = {}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t", timeout=900) as c:
            # 1. query -> awaiting_clarify
            r = await c.post("/api/v2/tasks", json={"query": QUERY})
            cj = r.json()
            summary["create_status_code"] = r.status_code
            summary["create_status"] = cj.get("status")
            summary["clarify_questions"] = cj.get("questions", [])
            summary["clarify_question_ids"] = [q.get("id") for q in cj.get("questions", [])]
            tid = cj["task_id"]
            assert cj.get("status") == "awaiting_clarify", f"expected awaiting_clarify, got {cj}"

            # 2. submit clarify answers -> run
            answers = []
            for q in cj.get("questions", []):
                if q.get("type") == "multi":
                    answers.append({"id": q.get("id"), "value": q.get("options", [])[:2]})
                else:
                    opts = q.get("options") or ["不限"]
                    answers.append({"id": q.get("id"), "value": opts[0]})
            sub = await c.post(f"/api/v2/tasks/{tid}/clarify", json={"answers": answers})
            summary["clarify_submit_status"] = sub.status_code
            summary["clarify_submit_body"] = sub.json()
            status = await _poll(c, tid, "clarify-task")
            summary["task_status"] = status

            # 3. evidences
            ev = (await c.get("/api/v2/evidences?limit=50")).json()
            summary["evidence_count"] = len(ev.get("items", []))
            summary["evidence_facets_total"] = ev.get("facets", {}).get("total", 0)
            summary["evidence_by_type"] = ev.get("facets", {}).get("by_type", {})

            # 4. dashboard
            dash = (await c.get("/api/v2/dashboard")).json()
            summary["dashboard_reports"] = dash.get("reports")
            summary["dashboard_evidence_total"] = dash.get("evidence_total")
            summary["dashboard_token_total"] = dash.get("token_total")
            summary["dashboard_tasks_by_status"] = dash.get("tasks_by_status")

            # 5. subscription run
            sc = await c.post("/api/v2/subscriptions", json={"query": QUERY, "brands": ["Cursor"]})
            summary["subscription_create"] = sc.json()
            sub_id = sc.json()["sub_id"]
            run = await c.post(f"/api/v2/subscriptions/{sub_id}/run")
            summary["subscription_run_status"] = run.status_code
            summary["subscription_run_body"] = run.json()
            if run.status_code == 202:
                sub_tid = run.json()["task_id"]
                sub_status = await _poll(c, sub_tid, "subscription-task", timeout=840)
                summary["subscription_task_status"] = sub_status
                listed = (await c.get("/api/v2/subscriptions")).json()["subscriptions"]
                s = next((x for x in listed if x["sub_id"] == sub_id), {})
                summary["subscription_run_count"] = s.get("run_count")
                summary["subscription_last_task_id"] = s.get("last_task_id")

            (OUT / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        await state.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
