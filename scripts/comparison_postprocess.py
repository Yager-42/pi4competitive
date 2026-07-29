"""Post-process comparison experiment: extract full stats from each group's JSONL.

Fixes the six-stage stat-extraction bug in _run_one_group.py (which couldn't
import extraction module / had a coroutine bug) by reading the session JSONL
directly. Produces a unified comparison table.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path("/Users/huangyaokai/pi4competitive")
WORKTREE = ROOT / ".claude/worktrees/v011-six-stage"
OUT = ROOT / "data/live_runs/comparison_v021"

# authoritative source domains (official + reputable media) vs aggregator/weak
AUTHORITATIVE_DOMAINS = {
    "apple.com", "apple.com.cn", "mi.com", "xiaomi.com",
    "cursor.com", "cursor.sh", "codeium.com", "windsurf.com", "codeium.com",
    "trae.com", "www.trae.com", "bytedance.com",
    "ithome.com", "gsmarena.com", "notebookcheck.com", "notebookcheck-cn.com",
    "36kr.com", "sspai.com", "ifanr.com", "geekpark.net",
    "wikipedia.org", "zh.wikipedia.org", "baike.baidu.com",
}
WEAK_DOMAINS = {
    "jiuphone.com", "jb51.net", "52ggi.cn", "m.jb51.net",
    "zhihu.com", "csdn.net", "blog.csdn.net", "jianshu.com",
}


def domain_of(url: str) -> str:
    s = url.split("//")[-1].split("/")[0].lower()
    return s


def is_authoritative(url: str) -> bool:
    d = domain_of(url)
    return any(d == a or d.endswith("." + a) for a in AUTHORITATIVE_DOMAINS)


def is_weak(url: str) -> bool:
    d = domain_of(url)
    return any(d == w or d.endswith("." + w) for w in WEAK_DOMAINS)


def extract_from_jsonl(session_path: Path, stage: str) -> dict:
    """Read a session JSONL; pull stage_output evidence + tool-call counts.

    Tool calls live INSIDE assistant message ``content`` blocks (type ``toolCall``,
    not as top-level entries). Six-stage collect's tool loop is one agent.prompt.
    Three-stage search sub-agents run on ephemeral InMemorySessionRepo harnesses
    (not persisted), so three-stage tool-call counts here capture only the plan
    stage + main harness — NOT the sub-agents' fetches. Three-stage fetch volume
    is better measured by SOCM evidence_nodes (each fetch → judge → evidence).
    """
    ev = []
    tool_calls = 0
    search_calls = 0
    fetch_calls = 0
    for line in session_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        t = e.get("type")
        if t == "custom_message" and e.get("details", {}).get("stage") == stage:
            content = e.get("content")
            if isinstance(content, dict):
                ev = content.get("evidence") or []
        # tool calls: dig into assistant message content blocks (type "toolCall")
        if t == "message":
            msg = e.get("message", e)
            content = msg.get("content")
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "toolCall":
                        tool_calls += 1
                        name = b.get("name") or ""
                        if name.endswith("_search"):
                            search_calls += 1
                        elif name.endswith("_fetch"):
                            fetch_calls += 1
    return {"evidence": ev, "tool_calls": tool_calls, "search_calls": search_calls, "fetch_calls": fetch_calls}


def find_session(repo_root: Path, cwd: str) -> Path | None:
    base = repo_root / "data/sessions" / f"--{cwd}--"
    if not base.is_dir():
        return None
    jsonls = sorted(base.glob("*.jsonl"))
    return jsonls[-1] if jsonls else None


def analyze_group(label: str, repo: Path, stage: str, cwd: str) -> dict:
    sess = find_session(repo, cwd)
    if sess is None:
        return {"label": label, "error": f"no session found for cwd={cwd} in {repo}"}
    j = extract_from_jsonl(sess, stage)
    ev = j["evidence"]
    srcs = {e.get("source") for e in ev if isinstance(e, dict) and e.get("source")}
    auth = {s for s in srcs if is_authoritative(s)}
    weak = {s for s in srcs if is_weak(s)}
    return {
        "label": label,
        "architecture": "three" if stage == "search" else "six",
        "stage": stage,
        "session": str(sess),
        "evidence_items": len(ev),
        "distinct_sources": len(srcs),
        "authoritative_sources": len(auth),
        "weak_sources": len(weak),
        "authoritative_ratio": round(len(auth) / len(srcs), 3) if srcs else 0.0,
        "tool_calls": j["tool_calls"],
        "search_calls": j["search_calls"],
        "fetch_calls": j["fetch_calls"],
        "sources_list": sorted(srcs),
        "authoritative_list": sorted(auth),
        "weak_list": sorted(weak),
    }


def merge_three_socm(label: str) -> dict:
    """Three-stage has SOCM with cell-level stats — merge those."""
    s = OUT / label / "summary.json"
    if not s.is_file():
        return {}
    d = json.loads(s.read_text(encoding="utf-8"))
    return {
        "total_cells": d.get("total_cells"),
        "filled": d.get("filled"),
        "unknown": d.get("unknown"),
        "conflict": d.get("conflict"),
        "junk_filled_cells": d.get("junk_filled_cells"),
        "multisource_cells": d.get("multisource_cells"),
        "iterations": d.get("iterations"),
        "budget_ratio": d.get("budget_ratio"),
    }


def main() -> None:
    groups = [
        ("three_t1", ROOT, "search", "comp_three_t1"),
        ("six_t1", WORKTREE, "collect", "comp_six_t1"),
        ("three_t2", ROOT, "search", "comp_three_t2"),
        ("six_t2", WORKTREE, "collect", "comp_six_t2"),
    ]
    results = {}
    for label, repo, stage, cwd in groups:
        r = analyze_group(label, repo, stage, cwd)
        if stage == "search":
            r["socm"] = merge_three_socm(label)
        results[label] = r
    (OUT / "comparison_stats.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Print compact table
    print("=" * 90)
    print(f"{'group':<12} {'arch':<6} {'evidence':<9} {'sources':<8} {'auth':<5} {'weak':<5} {'auth%':<6} {'tools':<6} {'cells':<6} {'multi':<6} {'junk':<5}")
    print("-" * 90)
    for label, r in results.items():
        if "error" in r:
            print(f"{label:<12} ERROR: {r['error']}")
            continue
        socm = r.get("socm") or {}
        cells = socm.get("total_cells", "-")
        multi = socm.get("multisource_cells", "-")
        junk = socm.get("junk_filled_cells", "-")
        print(
            f"{label:<12} {r['architecture']:<6} {r['evidence_items']:<9} {r['distinct_sources']:<8} "
            f"{r['authoritative_sources']:<5} {r['weak_sources']:<5} {r['authoritative_ratio']:<6} "
            f"{r['tool_calls']:<6} {str(cells):<6} {str(multi):<6} {str(junk):<5}"
        )
    print("=" * 90)


if __name__ == "__main__":
    main()
