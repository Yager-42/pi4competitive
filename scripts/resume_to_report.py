"""Resume a stopped-after-search task to produce the final report.

Reuses the already-searched data (SOCM for three-stage, collect evidence for
six-stage) and runs ONLY the downstream stages (three: write; six: analyze→
write→review→cite). Saves the final report to disk.

Args via env:
  RESUME_REPO, RESUME_TASK_ID, RESUME_SESSION_ID, RESUME_APP_DB,
  RESUME_SESSIONS_ROOT, RESUME_SESSIONS_CWD, RESUME_OUT, RESUME_ARCH (three|six)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(os.environ["RESUME_REPO"])
TASK_ID = os.environ["RESUME_TASK_ID"]
SESSION_ID = os.environ["RESUME_SESSION_ID"]
APP_DB = os.environ["RESUME_APP_DB"]
SESSIONS_ROOT = os.environ["RESUME_SESSIONS_ROOT"]
SESSIONS_CWD = os.environ["RESUME_SESSIONS_CWD"]
OUT = Path(os.environ["RESUME_OUT"])
ARCH = os.environ["RESUME_ARCH"]

sys.path.insert(0, str(REPO / "competitive_app/src"))
sys.path.insert(0, str(REPO / "packages/ai/src"))
sys.path.insert(0, str(REPO / "packages/agent/src"))

# Load .env
envp = Path("/Users/huangyaokai/pi4competitive/.env")
if envp.is_file():
    for raw in envp.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))

os.environ["SESSIONS_ROOT"] = SESSIONS_ROOT
os.environ["SESSIONS_CWD"] = SESSIONS_CWD
os.environ["APP_DB"] = APP_DB


async def prepare_task_for_resume(state: Any) -> None:
    """Prepare through the public service transaction before runner startup."""
    await state.task_service.prepare_resume_task(TASK_ID)
    print(f"[{ARCH}] reset task {TASK_ID} → pending, stripped stop_after_stage")


async def main() -> None:
    from httpx import ASGITransport, AsyncClient

    from competitive_app.adapter.in_.fastapi.app import create_app
    from competitive_app.wiring import build_application_state, load_config_from_env

    state = await build_application_state(load_config_from_env())
    app = create_app()
    app.state.application = state
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        await prepare_task_for_resume(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t", timeout=900) as c:
            t0 = time.time()
            r = await c.post(f"/api/v2/tasks/{TASK_ID}/resume")
            print(f"[{ARCH}] resume response: {r.status_code} {r.json() if r.status_code!=200 else ''}")
            status = "pending"
            while time.time() - t0 < 840:
                g = await c.get(f"/api/v2/tasks/{TASK_ID}")
                status = g.json().get("status")
                if status in {"completed", "failed", "aborted"}:
                    break
                await asyncio.sleep(4)
            if status not in {"completed", "failed", "aborted"}:
                raise TimeoutError(
                    f"task {TASK_ID} did not reach a terminal state before timeout "
                    f"(status={status!r})"
                )
            if status != "completed":
                raise RuntimeError(f"task {TASK_ID} ended with status {status!r}")
            elapsed = time.time() - t0
            proj = (await c.get(f"/api/v2/tasks/{TASK_ID}")).json()["projection"]
            rep = (await c.get(f"/api/v2/tasks/{TASK_ID}/report")).json()
            report_md = rep.get("report") or ""
            (OUT / f"report_{ARCH}.md").write_text(report_md, encoding="utf-8")
            (OUT / f"projection_{ARCH}.json").write_text(
                json.dumps(proj, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"[{ARCH}] DONE status={status} elapsed={elapsed:.0f}s stages={proj.get('stages')}")
            print(f"[{ARCH}] report chars: {len(report_md)}")
            print(f"[{ARCH}] saved: {OUT}/report_{ARCH}.md")
    finally:
        await state.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
