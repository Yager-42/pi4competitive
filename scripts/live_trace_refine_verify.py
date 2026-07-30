"""Live verify: trace spans + refine + feedback (v0.3.2 / v0.2.2).

Runs a real three-stage task, then:
1. GET /tasks/{id}/trace — verify spans (plan/write + subagent/judge)
2. POST /reports/{id}/refine — rewrite section 1
3. POST /reports/{id}/feedback — record revision rate
4. GET /reports/{id} — verify reflects refine (refine > write) + sections
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

envp = ROOT / ".env"
if envp.is_file():
    for raw in envp.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))

BRIEF = {
    "research_brief": {
        "target": {"name": "小米17", "category": "中国大陆旗舰手机"},
        "goal": "对比小米17与iPhone17的定价与硬件规格",
        "competitors": ["小米17", "iPhone17"],
        "dimensions": ["pricing", "specs"],
    },
    "metadata": {"trace": "live-trace-refine-verify"},
}
OUT = ROOT / "data/live_runs/trace_refine_verify"
OUT.mkdir(parents=True, exist_ok=True)
os.environ["SESSIONS_CWD"] = "live_trace_refine"
os.environ["SESSIONS_ROOT"] = str(ROOT / "data/sessions")
os.environ["APP_DB"] = str(OUT / "app.db")


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
            t0 = time.time()
            r = await c.post("/api/v2/tasks", json=BRIEF)
            tid = r.json()["task_id"]
            # poll to completion
            status = "pending"
            while time.time() - t0 < 840:
                g = await c.get(f"/api/v2/tasks/{tid}")
                status = g.json().get("status")
                if status in {"completed", "failed", "aborted"}:
                    break
                await asyncio.sleep(5)
            summary["task_id"] = tid
            summary["status"] = status
            summary["elapsed"] = round(time.time() - t0, 1)

            # 1. trace
            tr = await c.get(f"/api/v2/tasks/{tid}/trace")
            spans = tr.json().get("spans", [])
            from collections import Counter

            summary["trace_span_count"] = len(spans)
            summary["trace_kinds"] = dict(Counter(s["kind"] for s in spans))
            summary["trace_total_latency_ms"] = sum(s["latency_ms"] for s in spans)

            # 2. report (to find a section id)
            rep = await c.get(f"/api/v2/reports/{tid}")
            rj = rep.json()
            sections = rj.get("sections") or []
            summary["report_sections"] = len(sections)
            summary["report_has_sections_field"] = "sections" in rj
            sid = sections[0]["id"] if sections else None

            # 3. refine section 1
            if sid:
                rf = await c.post(
                    f"/api/v2/reports/{tid}/refine",
                    json={"section_id": sid, "annotations": ["补充更详细的定价数据与对比"]},
                )
                summary["refine_status"] = rf.status_code
                summary["refine_response"] = rf.json()
                # re-fetch report — should reflect refine
                after = (await c.get(f"/api/v2/reports/{tid}")).json()
                refined = next((s for s in after.get("sections", []) if str(s.get("id")) == str(sid)), None)
                summary["refine_reflected"] = bool(refined and refined.get("refined"))

            # 4. feedback
            fb = await c.post(
                f"/api/v2/reports/{tid}/feedback",
                json={"edited_blocks": 2, "total_blocks": 5, "data": {"note": "live verify"}},
            )
            summary["feedback_status"] = fb.status_code
            summary["feedback_response"] = fb.json()

            (OUT / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        await state.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
