"""Run ONE comparison group (invoked by comparison_experiment.py via subprocess).

Reads env: GROUP_LABEL, GROUP_REPO, GROUP_STOP_AFTER, GROUP_TRACE, GROUP_BRIEF, GROUP_OUT.
Sets sys.path to the target repo (main repo = three-stage; worktree = six-stage),
loads .env, POSTs a task with stop_after_stage in metadata, polls to completion,
saves SOCM + projection + evidence + quality summary.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

LABEL = os.environ["GROUP_LABEL"]
REPO = Path(os.environ["GROUP_REPO"])
STOP_AFTER = os.environ["GROUP_STOP_AFTER"]
TRACE = os.environ["GROUP_TRACE"]
BRIEF = json.loads(os.environ["GROUP_BRIEF"])
OUT = Path(os.environ["GROUP_OUT"])
OUT.mkdir(parents=True, exist_ok=True)

# sys.path → target repo's competitive_app + packages
sys.path.insert(0, str(REPO / "competitive_app/src"))
sys.path.insert(0, str(REPO / "packages/ai/src"))
sys.path.insert(0, str(REPO / "packages/agent/src"))

# Load .env (always the main repo's .env — same keys)
envp = Path("/Users/huangyaokai/pi4competitive/.env")
if envp.is_file():
    for raw in envp.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))

os.environ["SESSIONS_CWD"] = f"comp_{LABEL}"
os.environ["SESSIONS_ROOT"] = str(REPO / "data/sessions")
os.environ["APP_DB"] = str(OUT / "app.db")

BRIEF_FULL = {"research_brief": BRIEF["research_brief"], "metadata": {"trace": TRACE, "stop_after_stage": STOP_AFTER}}


async def main() -> None:
    from httpx import ASGITransport, AsyncClient

    from competitive_app.adapter.in_.fastapi.app import create_app
    from competitive_app.wiring import build_application_state, load_config_from_env

    state = await build_application_state(load_config_from_env())
    app = create_app()
    app.state.application = state
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t", timeout=900) as c:
            t0 = time.time()
            r = await c.post("/api/v2/tasks", json=BRIEF_FULL)
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
            if status not in {"completed", "failed", "aborted"}:
                raise TimeoutError(
                    f"task {tid} did not reach a terminal state before timeout (status={status!r})"
                )
            elapsed = time.time() - t0
            proj = (await c.get(f"/api/v2/tasks/{tid}")).json()["projection"]

            # Save projection
            (OUT / "projection.json").write_text(
                json.dumps(proj, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # SOCM (three-stage only — six-stage has no SOCM)
            summary: dict = {
                "label": LABEL,
                "architecture": "three" if STOP_AFTER == "search" else "six",
                "task_id": tid,
                "session_id": sid,
                "status": status,
                "stages": proj["stages"],
                "stop_after": STOP_AFTER,
            }
            try:
                from competitive_app.adapter.out.persistence.socm_store import SocmStore
                from competitive_app.domain.socm import CellStatus

                store = SocmStore(os.environ["SESSIONS_ROOT"])
                socm = await store.load(sid)
                (OUT / "socm.json").write_text(socm.model_dump_json(indent=2), encoding="utf-8")
                cm = socm.coverage_map
                status_counts = Counter(c.status.value for c in cm.cells.values())
                nodes = socm.evidence_graph.nodes
                sources = {n.source for n in nodes if n.source}
                node_by_cell = defaultdict(list)
                for n in nodes:
                    node_by_cell[(n.entity, n.attribute)].append(n)
                multisource = sum(1 for v in node_by_cell.values() if len({x.source for x in v}) >= 2)
                from competitive_app.application.workflow.extraction import _is_junk_value

                junk_cells = [
                    (c.entity_id, c.attribute_id, c.value)
                    for c in cm.cells.values()
                    if c.status == CellStatus.FILLED and _is_junk_value(c.value)
                ]
                summary.update(
                    {
                        "total_cells": len(cm.cells),
                        "cell_status_counts": dict(status_counts),
                        "filled": status_counts.get("filled", 0),
                        "unknown": status_counts.get("unknown", 0),
                        "conflict": status_counts.get("conflict", 0),
                        "evidence_nodes": len(nodes),
                        "distinct_sources": len(sources),
                        "multisource_cells": multisource,
                        "junk_filled_cells": len(junk_cells),
                        "iterations": socm.iteration,
                        "budget_ratio": socm.budget.ratio(),
                        "consumed_queries": socm.budget.consumed_queries,
                        "sources_list": sorted(sources),
                    }
                )
            except Exception as e:  # noqa: BLE001
                summary["socm_error"] = f"{type(e).__name__}: {e}"

            # Six-stage: count evidence from collect stage_output (no SOCM).
                try:
                    from competitive_app.application.workflow.stage_outputs import get_stage_output

                    session = await _open_session(state, sid)
                    collect_out = await get_stage_output(session, "collect")
                    evidence = (collect_out or {}).get("evidence") or []
                    srcs = {e.get("source") for e in evidence if isinstance(e, dict) and e.get("source")}
                    summary.update(
                        {
                            "evidence_items": len(evidence),
                            "distinct_sources": len(srcs),
                            "sources_list": sorted(srcs),
                        }
                    )
                    (OUT / "collect_evidence.json").write_text(
                        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                except Exception as e:  # noqa: BLE001
                    summary["collect_evidence_error"] = f"{type(e).__name__}: {e}"

            (OUT / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        await state.shutdown()


async def _open_session(state, sid):
    items = await state.repo.list({"cwd": os.environ["SESSIONS_CWD"]})
    meta = next((it for it in items if it["id"] == sid), None)
    if meta is None:
        raise RuntimeError(f"session {sid} not found in {os.environ['SESSIONS_CWD']}")
    return await state.repo.open(meta)


if __name__ == "__main__":
    asyncio.run(main())
