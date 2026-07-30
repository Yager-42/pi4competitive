"""Live verify: SSE stream of a real three-stage run (v0.3.1).

POSTs a task, connects to /tasks/{id}/stream, drains the event stream to
done/error, prints the event sequence + counts. Saves artifacts to OUT.
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
    "metadata": {"trace": "live-sse-verify"},
}
OUT = ROOT / "data/live_runs/sse_verify"
OUT.mkdir(parents=True, exist_ok=True)
os.environ["SESSIONS_CWD"] = "live_sse_verify"
os.environ["SESSIONS_ROOT"] = str(ROOT / "data/sessions")
os.environ["APP_DB"] = str(OUT / "app.db")


async def main() -> None:
    from httpx import ASGITransport, AsyncClient

    from competitive_app.adapter.in_.fastapi.app import create_app
    from competitive_app.wiring import build_application_state, load_config_from_env

    state = await build_application_state(load_config_from_env())
    app = create_app()
    app.state.application = state
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t", timeout=900) as c:
            r = await c.post("/api/v2/tasks", json=BRIEF)
            tid = r.json()["task_id"]
            print(f"task_id={tid}, connecting SSE...", flush=True)
            t0 = time.time()
            events: list = []
            async with c.stream("GET", f"/api/v2/tasks/{tid}/stream", timeout=900) as resp:
                print(f"SSE status={resp.status_code}", flush=True)
                etype = None
                dlines: list = []
                async for line in resp.aiter_lines():
                    if line.startswith(":"):
                        continue
                    if line.startswith("event: "):
                        etype = line[7:].strip()
                    elif line.startswith("data: "):
                        dlines.append(line[6:])
                    elif line == "" and etype is not None:
                        data = json.loads("".join(dlines)) if dlines else {}
                        events.append((etype, data))
                        if etype in {"done", "error"}:
                            break
                        etype = None
                        dlines = []
            elapsed = time.time() - t0
            types = [t for t, _ in events]
            from collections import Counter

            counts = Counter(types)
            summary = {
                "task_id": tid,
                "elapsed_seconds": round(elapsed, 1),
                "total_events": len(events),
                "event_counts": dict(counts),
                "first_event": types[0] if types else None,
                "last_event": types[-1] if types else None,
                "has_stage_start": "stage_start" in counts,
                "has_stage_end": "stage_end" in counts,
                "has_coverage_update": "coverage_update" in counts,
                "has_evidence": "evidence" in counts,
                "has_report_ready": "report_ready" in counts,
                "has_done": "done" in counts,
                "has_snapshot": "state_snapshot" in counts,
                "evidence_count": counts.get("evidence", 0),
                "coverage_updates": counts.get("coverage_update", 0),
            }
            (OUT / "sse_events.json").write_text(
                json.dumps([{"type": t, "data": d} for t, d in events], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (OUT / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        await state.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
