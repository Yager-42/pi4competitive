"""Three-stage vs six-stage SEARCH-QUALITY comparison (research-workflow-v1 v0.2.1).

Runs 4 groups (2 topics × 2 architectures), each stopping after the search stage
(three-stage: stop_after=search; six-stage: stop_after=collect) — NO final report,
to save cost. Six-stage collect is budget-capped (COLLECT_BUDGET) to align with
three-stage's search budget.

Each group runs in a subprocess with the right sys.path (main repo vs worktree).
Outputs per-group SOCM/evidence/projection + a comparison report.

Topics:
  1. Xiaomi17 vs iPhone17 (China) — pricing/specs/features
  2. trae vs Cursor vs Windsurf — pricing/features/models
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/Users/huangyaokai/pi4competitive")
WORKTREE = ROOT / ".claude/worktrees/v011-six-stage"
VENV = ROOT / ".venv/bin/python"
OUT = ROOT / "data/live_runs/comparison_v021"
OUT.mkdir(parents=True, exist_ok=True)

BRIEF_T1 = {
    "research_brief": {
        "target": {"name": "小米17", "category": "中国大陆旗舰手机"},
        "goal": "对比中国大陆市场小米17与iPhone17的定价(人民币)、硬件规格、功能差异,面向国内消费者购买决策",
        "competitors": ["小米17", "iPhone17"],
        "dimensions": ["pricing", "specs", "features"],
    }
}
BRIEF_T2 = {
    "research_brief": {
        "target": {"name": "trae", "category": "AI-native IDE (字节跳动)"},
        "goal": "对比 trae、Cursor、Windsurf 三款 AI IDE 的定价、功能特性、底层模型,面向开发者选型决策",
        "competitors": ["trae", "Cursor", "Windsurf"],
        "dimensions": ["pricing", "features", "models"],
    }
}

# Three-stage search budget measured on topic 1: 8 subtasks (consumed_queries),
# ~135 evidence nodes (many fetches). Give six-stage collect a comparable call budget.
# Three-stage sub-agents do ~3-5 tool calls each × 8 = ~30-40 calls. Use 30.
COLLECT_BUDGET = "30"


def run_group(label: str, repo: Path, brief: dict, stop_after: str, trace: str) -> dict:
    """Run one group in a subprocess; return summary dict."""
    runner = ROOT / "scripts/_run_one_group.py"
    env = os.environ.copy()
    env["GROUP_LABEL"] = label
    env["GROUP_REPO"] = str(repo)
    env["GROUP_STOP_AFTER"] = stop_after
    env["GROUP_TRACE"] = trace
    env["GROUP_BRIEF"] = json.dumps(brief, ensure_ascii=False)
    env["GROUP_OUT"] = str(OUT / label)
    if stop_after == "collect":
        env["COLLECT_BUDGET"] = COLLECT_BUDGET
    t0 = time.time()
    proc = subprocess.run(
        [str(VENV), str(runner)], env=env, capture_output=True, text=True, timeout=900
    )
    elapsed = time.time() - t0
    log_path = OUT / f"{label}.log"
    log_path.write_text(proc.stdout + "\n--- STDERR ---\n" + proc.stderr, encoding="utf-8")
    summary_path = OUT / label / "summary.json"
    summary = {}
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["elapsed_seconds"] = round(elapsed, 1)
    summary["returncode"] = proc.returncode
    summary["label"] = label
    if proc.returncode != 0:
        summary["error"] = proc.stderr[-500:] if proc.stderr else "nonzero exit"
    print(f"[{label}] rc={proc.returncode} elapsed={summary['elapsed_seconds']}s status={summary.get('status')}")
    return summary


def main() -> None:
    groups = [
        ("three_t1", ROOT, BRIEF_T1, "search", "comp-three-t1"),
        ("six_t1", WORKTREE, BRIEF_T1, "collect", "comp-six-t1"),
        ("three_t2", ROOT, BRIEF_T2, "search", "comp-three-t2"),
        ("six_t2", WORKTREE, BRIEF_T2, "collect", "comp-six-t2"),
    ]
    results = {}
    for label, repo, brief, stop_after, trace in groups:
        results[label] = run_group(label, repo, brief, stop_after, trace)

    (OUT / "all_summaries.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n=== ALL GROUPS DONE ===")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
