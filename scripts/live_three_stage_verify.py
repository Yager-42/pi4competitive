"""Live verify: three-stage search-quality fix (research-workflow-v1 v0.2.1).

Runs plan→search→write on the Xiaomi17 vs iPhone17 (China) brief, saves SOCM +
projection + evidence + report, and prints a quality summary so we can confirm
the Tier-0/1/2 fixes took effect (multi-source, no junk, UNKNOWN reachable,
cell re-dispatch).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path("/Users/huangyaokai/pi4competitive")
sys.path.insert(0, str(ROOT / "competitive_app" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "ai" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "agent" / "src"))

# Load .env
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
        "goal": "对比中国大陆市场小米17与iPhone17的定价(人民币)、硬件规格、功能差异,面向国内消费者购买决策",
        "competitors": ["小米17", "iPhone17"],
        "dimensions": ["pricing", "specs", "features"],
    },
    "metadata": {"trace": "three-stage-v021-verify"},
}
OUT = ROOT / "data/live_runs/xiaomi17_vs_iphone17_cn_FIXED"
OUT.mkdir(parents=True, exist_ok=True)
os.environ["SESSIONS_CWD"] = "live_three_verify"
os.environ["SESSIONS_ROOT"] = str(ROOT / "data/sessions")
os.environ["APP_DB"] = str(OUT / "app.db")


async def main() -> None:
    from competitive_app.adapter.in_.fastapi.app import create_app
    from competitive_app.wiring import build_application_state, load_config_from_env
    from httpx import ASGITransport, AsyncClient

    state = await build_application_state(load_config_from_env())
    app = create_app()
    app.state.application = state
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t", timeout=900) as c:
            t0 = time.time()
            r = await c.post("/api/v2/tasks", json=BRIEF)
            body = r.json()
            tid = body["task_id"]
            sid = body["session_id"]
            status = "pending"
            while time.time() - t0 < 840:
                g = await c.get(f"/api/v2/tasks/{tid}")
                status = g.json().get("status")
                if status in {"completed", "failed", "aborted"}:
                    break
                await asyncio.sleep(5)
            elapsed = time.time() - t0
            proj = (await c.get(f"/api/v2/tasks/{tid}")).json()["projection"]
            rep = (await c.get(f"/api/v2/tasks/{tid}/report")).json()
            report_md = rep.get("report") or ""

            # SOCM artifact
            from competitive_app.adapter.out.persistence.socm_store import SocmStore

            store = SocmStore(os.environ["SESSIONS_ROOT"])
            socm = await store.load(sid)

            (OUT / "report.md").write_text(report_md, encoding="utf-8")
            (OUT / "socm.json").write_text(socm.model_dump_json(indent=2), encoding="utf-8")
            (OUT / "projection.json").write_text(
                json.dumps(proj, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # Quality summary
            cm = socm.coverage_map
            from collections import Counter

            status_counts = Counter(c.status.value for c in cm.cells.values())
            nodes = socm.evidence_graph.nodes
            sources = {n.source for n in nodes if n.source}
            # multi-source cells: cells whose candidates > 1, OR filled cells supported by >1 node
            from collections import defaultdict

            node_by_cell = defaultdict(list)
            for n in nodes:
                node_by_cell[(n.entity, n.attribute)].append(n)
            multisource = sum(1 for v in node_by_cell.values() if len({x.source for x in v}) >= 2)
            junk_cells = [
                (c.entity_id, c.attribute_id, c.value)
                for c in cm.cells.values()
                if c.status == CellStatus_FILLED and _is_junk(c.value)
            ]

            summary = {
                "task_id": tid,
                "session_id": sid,
                "status": status,
                "elapsed_seconds": round(elapsed, 1),
                "stages": proj["stages"],
                "coverage": proj.get("coverage"),
                "cell_status_counts": dict(status_counts),
                "total_cells": len(cm.cells),
                "filled": status_counts.get("filled", 0),
                "unknown": status_counts.get("unknown", 0),
                "conflict": status_counts.get("conflict", 0),
                "evidence_nodes": len(nodes),
                "distinct_sources": len(sources),
                "multisource_cells": multisource,
                "junk_filled_cells": len(junk_cells),
                "iterations": socm.iteration,
                "budget_ratio": socm.budget.ratio(),
                "sources_list": sorted(sources),
            }
            (OUT / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        await state.shutdown()


def _is_junk(value: str) -> bool:
    from competitive_app.application.workflow.extraction import _is_junk_value

    return _is_junk_value(value or "")


# avoid name shadowing at module import time
CellStatus_FILLED = None


async def _go():
    global CellStatus_FILLED
    from competitive_app.domain.socm import CellStatus

    CellStatus_FILLED = CellStatus.FILLED
    await main()


if __name__ == "__main__":
    asyncio.run(_go())
