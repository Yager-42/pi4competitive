"""One-off smoke: Claude Code (headless ``claude -p``) vs A2 on DRB II cases.

Runs Claude Code as a research agent on one or more DRB II briefs, captures its
final Markdown report + JSON run metadata, normalizes each report through the
same pipeline as the eval harness, and scores them with the SAME rubric LLM
judge used for the A2 baseline (eval/evaluator/drb2.py, gpt-5.6-luna via env
gateway). Then prints a per-case comparison against the documented A2 baseline.

NOT part of the eval harness (one-off experiment). Output follows the harness
layout so existing tooling could read it:

    data/evaluations/<run_id>/
      raw/drb2/<case>/<variant>/0/report.md      raw cc report
      raw/drb2/<case>/<variant>/0/claude.json    claude -p result object (repro)
      normalized/drb2_reports/<variant>_<case>_0.md
      scores/drb2.jsonl                          cc ScoreRows (from evaluator)
      summary/cc_vs_a2.md                        comparison table
      summary/metrics.json                       cc meta + A2 reference

Run in WSL (real env) with the workspace venv and .env:

    cp scripts/cc_drb2_smoke.py /root/pi4competitive/scripts/
    wsl -e bash -lc 'cd /root/pi4competitive && \\
      export PYTHONPATH=$PWD/competitive_app/src:$PWD/packages/agent/src:$PWD/packages/ai/src:$PWD/eval/src && \\
      set -a; . ./.env; set +a; \\
      ./.venv/bin/python scripts/cc_drb2_smoke.py --cases drb2_4,drb2_6,drb2_18,drb2_22,drb2_30'

Per-case stop conditions for the claude -p subprocess (any one stops it):
  1. natural end_turn (agent finishes its report)
  2. --max-turns reached (agentic turn cap)
  3. --budget-usd reached (cost cap)
  4. --timeout-s / outer bash timeout (external kill)
Whatever report exists at stop time is normalized + judged.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# ---------------------------------------------------------------- bootstrap

REPO_ROOT = Path(__file__).resolve().parents[1]
for _rel in ("eval/src", "competitive_app/src", "packages/agent/src", "packages/ai/src"):
    _p = REPO_ROOT / _rel
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load_dotenv(root: Path) -> None:
    """Parse root/.env KEY=VALUE lines (setdefault semantics, like tests/live_env)."""
    env_file = root / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


# Documented A2 baseline (competitorlens, gpt-5.6-luna judge, prior harness run —
# 基准文档 §2.6 / §4.3). Per-case TOTAL from the §4.3 full-run table; per-dimension
# breakdown is only published for drb2_22 (§2.6). Same-pass re-judging of A2
# (if its reports exist on the WSL worktree) is a follow-up.
A2_DOC: dict[str, dict[str, float]] = {
    "drb2_4":  {"total": 0.140},
    "drb2_6":  {"total": 0.433},
    "drb2_18": {"total": 0.434},
    "drb2_22": {"info_recall": 0.000, "analysis": 0.769, "presentation": 0.857, "total": 0.542},
    "drb2_30": {"total": 0.258},
}


def _claude_prompt(brief: str) -> str:
    """Build the Claude Code system+user prompt for a DRB II brief."""
    return (
        "You are a professional research analyst writing an in-depth research report. "
        "Complete the research task in the brief below.\n\n"
        "You MUST actively use the WebSearch tool to gather evidence from authoritative "
        "primary and secondary sources, and WebFetch to open the most promising results. "
        "Do not rely on prior knowledge alone.\n\n"
        "When your research is complete, BEFORE finishing: use the Write tool to save the "
        "entire final report to a file named report.md in the current directory. Then output "
        "the same complete report as your very last message. This file is your safety net — "
        "write it even if you must skip some polish.\n\n"
        "CRITICAL RULE — blocked references: the brief contains an \"important\" rule "
        "listing specific articles and URLs you must NOT view or quote. Obey it exactly: "
        "never open those URLs, never cite those articles or anything you saw there. "
        "This is a hard constraint, not optional.\n\n"
        "Be efficient with tool turns. Focus your searches on the exact facts, figures, "
        "and tables the brief asks for, and verify numbers by opening sources.\n\n"
        "When your research is complete, output your ENTIRE final report as ONE "
        "self-contained Markdown document as your very last message. Structure it exactly "
        "as the brief requests — the sections and tables it names, with the exact columns "
        "it specifies. Cite sources with inline URLs.\n\n"
        f"--- RESEARCH BRIEF ---\n\n{brief}"
    )


def _run_claude(prompt: str, *, workdir: Path, max_turns: int, budget_usd: float, timeout_s: float) -> dict:
    """Run ``claude -p`` headless with web tools; return parsed JSON result object.

    stdin is DEVNULL (CLI hangs if stdin is left open — documented gotcha).
    --no-session-persistence keeps the run off ~/.claude/projects.
    """
    cmd = [
        "claude",
        "-p",
        prompt,
        "--output-format", "json",
        "--permission-mode", "bypassPermissions",
        "--allowedTools", "WebSearch,WebFetch,Write",
        "--no-session-persistence",
        "--max-turns", str(max_turns),
        "--max-budget-usd", str(budget_usd),
    ]
    start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workdir),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        return {"_rc": -1, "_timeout": True, "_wall_s": round(time.time() - start, 1),
                "result": exc.stdout if exc.stdout else "", "subtype": "timeout"}
    wall = time.time() - start
    obj: dict = {}
    if proc.stdout.strip():
        try:
            obj = json.loads(proc.stdout)
        except json.JSONDecodeError:
            obj = {"_parse_error": proc.stdout[:2000]}
    obj["_rc"] = proc.returncode
    obj["_wall_s"] = round(wall, 1)
    if proc.stderr:
        obj["_stderr_tail"] = proc.stderr.strip()[-800:]
    return obj


def _model_meta(obj: dict) -> dict:
    """Flatten the per-model usage + top-level result fields we care about."""
    mu = obj.get("modelUsage") or {}
    model = next(iter(mu), "unknown")
    return {
        "model": model,
        "subtype": obj.get("subtype"),
        "is_error": obj.get("is_error"),
        "num_turns": obj.get("num_turns"),
        "stop_reason": obj.get("stop_reason"),
        "total_cost_usd": obj.get("total_cost_usd"),
        "duration_ms": obj.get("duration_ms"),
        "model_usage": mu.get(model) if model in mu else mu,
        "_rc": obj.get("_rc"),
        "_wall_s": obj.get("_wall_s"),
        "_timeout": obj.get("_timeout", False),
    }


def main() -> int:
    p = argparse.ArgumentParser(prog="cc_drb2_smoke", description=__doc__)
    p.add_argument("--cases", default="drb2_22", help="comma-separated case ids")
    p.add_argument("--variant", default="cc")
    p.add_argument("--manifest", default="eval/manifests/drb2_smoke.jsonl")
    p.add_argument("--dataset", default="data/benchmarks/drb2/tasks_and_rubrics.jsonl")
    p.add_argument("--out-root", default="data/evaluations")
    p.add_argument("--max-turns", type=int, default=60)
    p.add_argument("--timeout-s", type=float, default=1500.0)
    p.add_argument("--budget-usd", type=float, default=10.0)
    p.add_argument("--judge-max-items", type=int, default=0, help="0 = full rubric (default)")
    p.add_argument(
        "--seed-report", default=None,
        help="skip the claude -p run and judge this existing .md/.txt report instead (single case only)",
    )
    p.add_argument(
        "--judge-cap", type=int, default=12000,
        help="report chars fed to judge (harness default 12000). 0 = no truncation.",
    )
    args = p.parse_args()

    if args.seed_report and len(args.cases.split(",")) > 1:
        print("--seed-report only supports a single case", file=sys.stderr)
        return 1

    _load_dotenv(REPO_ROOT)

    from eval.manifest import load_manifest
    from eval.normalizer.drb2 import normalize_report
    from eval.evaluator.drb2 import run_drb2_evaluation

    manifest_cases = load_manifest(REPO_ROOT / args.manifest)
    by_id = {c.source_task_id: c for c in manifest_cases}
    wanted = [c.strip() for c in args.cases.split(",") if c.strip()]
    missing = [c for c in wanted if c not in by_id]
    if missing:
        print(f"cases not in manifest: {missing}; have {sorted(by_id)}", file=sys.stderr)
        return 1
    cases = [by_id[c] for c in wanted]

    short_sha = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO_ROOT), text=True
    ).strip()
    run_id = f"cc-smoke-drb2-{args.variant}-{short_sha}"
    run_dir = Path(args.out_root) / run_id
    norm_dir = run_dir / "normalized" / "drb2_reports"
    scores_dir = run_dir / "scores"
    summary_dir = run_dir / "summary"
    for d in (run_dir / "raw" / "drb2", norm_dir, scores_dir, summary_dir):
        d.mkdir(parents=True, exist_ok=True)
    (run_dir / "claude_work").mkdir(parents=True, exist_ok=True)  # subprocess cwd must exist

    # ---- per-case: run claude (or seed) in PARALLEL, then normalize ---------
    def _run_case(case):
        raw_dir = run_dir / "raw" / "drb2" / case.case_id / args.variant / "0"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "request.json").write_text(
            json.dumps({"case_id": case.case_id, "variant": args.variant, "query": case.query},
                       ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        prompt = _claude_prompt(case.query)
        (raw_dir / "claude_prompt.txt").write_text(prompt, encoding="utf-8")
        workdir = run_dir / "claude_work" / case.case_id
        workdir.mkdir(parents=True, exist_ok=True)  # subprocess cwd must exist

        if args.seed_report:
            report = Path(args.seed_report).read_text(encoding="utf-8")
            obj = {"_rc": 0, "_wall_s": 0.0, "result": report, "subtype": "seeded",
                   "num_turns": 0, "_seed": str(args.seed_report)}
            print(f"[cc] {case.case_id}: seeded report {args.seed_report} ({len(report)} chars)")
        else:
            print(f"[cc] {case.case_id}: claude -p (max_turns={args.max_turns}, "
                  f"budget=${args.budget_usd}, timeout={args.timeout_s:.0f}s)...", flush=True)
            obj = _run_claude(prompt, workdir=workdir,
                              max_turns=args.max_turns, budget_usd=args.budget_usd,
                              timeout_s=args.timeout_s)
            report = obj.get("result") or ""
            # Safety net: budget-abort returns empty result, but the prompt asks
            # claude to Write the report to report.md in its cwd — fall back to it.
            if not report:
                written = workdir / "report.md"
                if written.is_file():
                    report = written.read_text(encoding="utf-8", errors="replace")
                    obj["_from_file"] = str(written)
                    obj["_file_chars"] = len(report)
            if not report:
                print(f"[cc] {case.case_id}: WARNING no result text "
                      f"(rc={obj.get('_rc')}, subtype={obj.get('subtype')})", file=sys.stderr)
            (raw_dir / "claude.json").write_text(
                json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
            src = "result" if obj.get("result") else ("file" if obj.get("_from_file") else "none")
            print(f"[cc] {case.case_id}: report {len(report)} chars (src={src}), rc={obj.get('_rc')}, "
                  f"subtype={obj.get('subtype')}, wall={obj.get('_wall_s')}s", flush=True)

        (raw_dir / "report.md").write_text(report or "", encoding="utf-8")
        return case, obj, report

    metas: dict[str, dict] = {}
    workers = 1 if args.seed_report else min(len(cases), 5)
    if workers > 1:
        print(f"[cc] running {len(cases)} claude processes in parallel (workers={workers})...", flush=True)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_run_case, cases))
    else:
        results = [_run_case(c) for c in cases]

    for case, obj, report in results:
        normalize_report(
            report_md=report or "",
            instance_id=case.case_id,
            model_config_name=args.variant,
            trial_idx=0,
            out_path=norm_dir / f"{args.variant}_{case.case_id}_0.md",
        )
        metas[case.case_id] = _model_meta(obj)

    # ---- one judge pass over all normalized reports (same settings as A2) ---
    max_items = int(os.environ.get("DRB2_MAX_ITEMS", "0") or 0) or None
    if args.judge_max_items:
        max_items = args.judge_max_items
    if args.judge_cap != 12000:
        import eval.evaluator.drb2 as _drb2mod
        _cap, _orig = args.judge_cap, _drb2mod._judge_prompt

        def _judge_prompt_no_trunc(task, item, report):
            return _orig(task, item, report if _cap == 0 else report[:_cap])

        _drb2mod._judge_prompt = _judge_prompt_no_trunc
    dataset = REPO_ROOT / args.dataset
    if not dataset.is_file():
        alt = Path("/mnt/d/python/pi4competitive") / args.dataset
        if alt.is_file():
            dataset = alt
        else:
            print(f"[cc] dataset not found: {dataset}", file=sys.stderr)
            return 3
    print(f"[cc] judging {len(cases)} case(s) (dataset={dataset}, "
          f"max_items={max_items or 'all'}, judge_cap={args.judge_cap or 'none'})...", flush=True)
    import asyncio
    rows = asyncio.run(
        run_drb2_evaluation(
            response_root=norm_dir,
            result_save_root=scores_dir / "drb2_raw",
            dataset_path=dataset,
            model_config_name=args.variant,
            trial_num=0,
            max_items=max_items,
        )
    )
    (scores_dir / "drb2.jsonl").write_text(
        "\n".join(json.dumps(r.to_dict(), ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    by_case = {r.instance_id: r for r in rows}

    # ---- summary -------------------------------------------------------------
    def _fmt(v) -> str:
        return "null" if v is None else f"{v:.3f}"

    lines = [
        f"# Claude Code vs A2 — DRB II ({len(cases)} case{'s' if len(cases)>1 else ''})",
        "",
        f"- run_id: `{run_id}` · variant: `{args.variant}`",
        f"- judge: `{os.environ.get('OPENAI_MODEL','')}` · judge_cap: {args.judge_cap or 'none'}",
        f"- A2 reference: documented baseline (§2.6/§4.3), not a same-pass re-judge",
        "",
        "| case | dim | A2 (ref) | cc | delta (cc−A2) |",
        "|---|---|---|---|---|",
    ]
    summary: dict = {
        "run_id": run_id, "variant": args.variant,
        "judge": {"model": os.environ.get("OPENAI_MODEL", ""),
                  "base_url": os.environ.get("OPENAI_BASE_URL", ""),
                  "max_items": max_items, "cap": args.judge_cap},
        "a2_reference_source": "doc baseline (gpt-5.6-luna judge, prior harness run)",
        "cases": {},
    }
    for case in cases:
        row = by_case.get(case.case_id)
        dims = ("info_recall", "analysis", "presentation", "total")
        if row is None:
            dims_vals = {d: None for d in dims}
        else:
            dims_vals = {d: getattr(row, d) for d in dims}
        a2 = A2_DOC.get(case.case_id, {})
        summary["cases"][case.case_id] = {
            "cc": dims_vals, "a2_reference": a2,
            "claude_meta": metas.get(case.case_id, {}),
        }
        for d in dims:
            cv, av = dims_vals.get(d), a2.get(d)
            delta = (cv - av) if (cv is not None and av is not None) else None
            if d == "total":
                lines.append(f"| **{case.case_id}** | **{d}** | **{_fmt(av)}** | **{_fmt(cv)}** | **{_fmt(delta)}** |")
            else:
                lines.append(f"| {case.case_id} | {d} | {_fmt(av)} | {_fmt(cv)} | {_fmt(delta)} |")

    lines.append("")
    lines.append("Note: harness judge truncates reports at 12000 chars (judge_cap). Long")
    lines.append("table-first reports put their analysis beyond the cut — check raw report")
    lines.append("§-offset if a dimension looks deflated; re-judge with --judge-cap 0.")
    (summary_dir / "cc_vs_a2.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (summary_dir / "metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nrun complete: {run_id}")
    print(f"  comparison: {summary_dir / 'cc_vs_a2.md'}")
    print("\n" + "\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
