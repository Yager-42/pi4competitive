"""Same-pass, full-visibility re-judge of A2 vs Claude Code (cc) on DRB II.

Places both systems' reports in ONE normalized dir and judges ALL of them in a
single judge pass with the same rubric judge (gpt-5.6-luna via env gateway), so
judge drift and truncation asymmetry are controlled for. The 5 cases are judged
in parallel (bounded by a semaphore, default 5).

    --judge-cap 0  = full report visibility (the harness judge truncates at 12000;
                     long table-first reports get their analysis cut off)
    --concurrency 5 = max concurrent gpt-5.6-luna judge calls (lower if the
                     gateway throttles)

Inputs:
    --cc-run  data/evaluations/cc-smoke-drb2-cc-f896509        (our one-off run)
    --a2-run  data/evaluations/smoke-drb2-1962711-f896509      (harness baseline)

Output (new dir, harness layout):
    data/evaluations/cc-vs-a2-samepass-<sha>/
      normalized/drb2_reports/{cc,competitorlens_a2}_<case>_0.md
      scores/drb2.jsonl + scores/drb2_raw/*_eval_result.json
      summary/cc_vs_a2.md   summary/metrics.json

Run in WSL (real env):
    cp scripts/cc_vs_a2_samepass.py /root/pi4competitive/scripts/
    wsl -e bash -lc 'cd /root/pi4competitive && \
      export PYTHONPATH=$PWD/competitive_app/src:$PWD/packages/agent/src:$PWD/packages/ai/src:$PWD/eval/src && \
      set -a; . ./.env; set +a; \
      ./.venv/bin/python scripts/cc_vs_a2_samepass.py \
        --cc-run data/evaluations/cc-smoke-drb2-cc-f896509 \
        --a2-run data/evaluations/smoke-drb2-1962711-f896509 \
        --judge-cap 0 --concurrency 5'
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------- bootstrap

REPO_ROOT = Path(__file__).resolve().parents[1]
for _rel in ("eval/src", "competitive_app/src", "packages/agent/src", "packages/ai/src"):
    _p = REPO_ROOT / _rel
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load_dotenv(root: Path) -> None:
    env_file = root / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_CASES = ["drb2_4", "drb2_6", "drb2_18", "drb2_22", "drb2_30"]


async def main() -> int:
    p = argparse.ArgumentParser(prog="cc_vs_a2_samepass", description=__doc__)
    p.add_argument("--cc-run", required=True, help="cc one-off run dir (has raw/drb2/<case>/cc/0/report.md)")
    p.add_argument("--a2-run", required=True, help="A2 baseline run dir (has raw/drb2/<case>/a2/0/report.md)")
    p.add_argument("--dataset", default="data/benchmarks/drb2/tasks_and_rubrics.jsonl")
    p.add_argument("--out-root", default="data/evaluations")
    p.add_argument("--judge-cap", type=int, default=0, help="report chars fed to judge; 0 = no truncation")
    p.add_argument("--concurrency", type=int, default=5, help="max concurrent judge calls")
    p.add_argument("--judge-max-items", type=int, default=0, help="0 = full rubric (default)")
    args = p.parse_args()

    _load_dotenv(REPO_ROOT)

    import eval.evaluator.drb2 as drb2

    if args.judge_cap != 12000:
        _cap, _orig = args.judge_cap, drb2._judge_prompt

        def _judge_prompt_patched(task, item, report):
            return _orig(task, item, report if _cap == 0 else report[:_cap])

        drb2._judge_prompt = _judge_prompt_patched

    dataset = REPO_ROOT / args.dataset
    if not dataset.is_file():
        alt = Path("/mnt/d/python/pi4competitive") / args.dataset
        if alt.is_file():
            dataset = alt
        else:
            print(f"dataset not found: {dataset}", file=sys.stderr)
            return 3

    short_sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO_ROOT), text=True).strip()
    out_dir = Path(args.out_root) / f"cc-vs-a2-samepass-{short_sha}"
    norm_dir = out_dir / "normalized" / "drb2_reports"
    scores_dir = out_dir / "scores"
    summary_dir = out_dir / "summary"
    for d in (norm_dir, scores_dir / "drb2_raw", summary_dir):
        d.mkdir(parents=True, exist_ok=True)

    cc_run, a2_run = Path(args.cc_run), Path(args.a2_run)
    # assemble the 10 reports under a shared normalized dir (distinct model_config_names)
    planned: list[tuple[str, str, Path]] = []  # (model_config_name, case, src_report)
    for mc, run, sub in (("cc", cc_run, "cc"), ("competitorlens_a2", a2_run, "a2")):
        for case in _CASES:
            src = run / "raw" / "drb2" / case / sub / "0" / "report.md"
            if not src.is_file():
                print(f"[warn] missing report: {src}", file=sys.stderr)
                continue
            planned.append((mc, case, src))
    if len(planned) < 10:
        print(f"expected 10 reports, have {len(planned)} — abort", file=sys.stderr)
        return 4

    for mc, case, src in planned:
        dst = norm_dir / f"{mc}_{case}_0.md"
        shutil.copyfile(src, dst)

    tasks = drb2.load_task_dataset(dataset)
    max_items = int(os.environ.get("DRB2_MAX_ITEMS", "0") or 0) or None
    if args.judge_max_items:
        max_items = args.judge_max_items
    judge = drb2.default_judge_fn
    sem = asyncio.Semaphore(args.concurrency)

    async def _bounded(task, item, report):
        async with sem:
            return await drb2._judge_item(task, item, report, judge)

    async def _judge_report(mc, case, report_file):
        report = report_file.read_text(encoding="utf-8")
        if args.judge_cap:
            report = report[: args.judge_cap]
        task = tasks.get(case)
        if task is None:
            return drb2.ScoreRow(case, mc, 0, None, None, None, None, failure_stage="missing_task")
        dims: dict[str, float] = {}
        try:
            for dim in drb2._DIMENSIONS:
                items = task["rubric"].get(dim) or []
                if max_items:
                    items = items[:max_items]
                judged = await asyncio.gather(*[_bounded(task, it, report) for it in items])
                dims[dim] = drb2._dimension_score(judged)
        except Exception:  # noqa: BLE001
            return drb2.ScoreRow(case, mc, 0, None, None, None, None, failure_stage="judge_error")
        total = drb2._total_score([dims.get(d) for d in drb2._DIMENSIONS if dims.get(d) is not None])
        return drb2.ScoreRow(
            case, mc, 0,
            dims.get("info_recall"), dims.get("analysis"), dims.get("presentation"), total,
        )

    print(f"[samepass] judging {len(planned)} reports (concurrency={args.concurrency}, "
          f"cap={args.judge_cap or 'none'}, max_items={max_items or 'all'})...", flush=True)
    rows = await asyncio.gather(*[_judge_report(mc, case, src) for mc, case, src in planned])

    # write scores
    (scores_dir / "drb2.jsonl").write_text(
        "\n".join(json.dumps(r.to_dict(), ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    for r in rows:
        (scores_dir / "drb2_raw" / f"{r.variant}_{r.instance_id}_0_eval_result.json").write_text(
            json.dumps(r.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    by = {(r.variant, r.instance_id): r for r in rows}

    def _fmt(v) -> str:
        return "null" if v is None else f"{v:.3f}"

    lines = [
        "# A2 vs Claude Code — same-pass full-visibility re-judge (DRB II)",
        "",
        f"- run: `{out_dir.name}`",
        f"- judge: `{os.environ.get('OPENAI_MODEL','')}` · judge_cap: {args.judge_cap or 'none'} · concurrency: {args.concurrency}",
        f"- reports: A2 from `{a2_run.name}`, cc from `{cc_run.name}`",
        "",
        "| case | dim | A2 (same-pass) | cc (same-pass) | delta (cc−A2) |",
        "|---|---|---|---|---|",
    ]
    dim_means = {d: {"a2": [], "cc": []} for d in ("info_recall", "analysis", "presentation", "total")}
    for case in _CASES:
        for d in ("info_recall", "analysis", "presentation", "total"):
            a = by.get(("competitorlens_a2", case))
            c = by.get(("cc", case))
            av = getattr(a, d) if a else None
            cv = getattr(c, d) if c else None
            delta = (cv - av) if (cv is not None and av is not None) else None
            for key, v in (("a2", av), ("cc", cv)):
                if v is not None:
                    dim_means[d][key].append(v)
            mark = "**" if d == "total" else ""
            lines.append(
                f"| {mark}{case}{mark} | {d} | {_fmt(av)} | {_fmt(cv)} | {_fmt(delta)} |"
            )
    lines.append("")
    for d in ("info_recall", "analysis", "presentation", "total"):
        a_m = sum(dim_means[d]["a2"]) / max(1, len(dim_means[d]["a2"]))
        c_m = sum(dim_means[d]["cc"]) / max(1, len(dim_means[d]["cc"]))
        lines.append(f"- mean {d}: A2 {a_m:.3f} · cc {c_m:.3f} · Δ {c_m - a_m:+.3f}")
    (summary_dir / "cc_vs_a2.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (summary_dir / "metrics.json").write_text(
        json.dumps({
            "judge": {"model": os.environ.get("OPENAI_MODEL", ""), "cap": args.judge_cap,
                      "concurrency": args.concurrency, "max_items": max_items},
            "a2_run": str(a2_run), "cc_run": str(cc_run),
            "rows": [r.to_dict() for r in rows],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\nrun complete: {out_dir}")
    print(f"  comparison: {summary_dir / 'cc_vs_a2.md'}")
    print("\n" + "\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
