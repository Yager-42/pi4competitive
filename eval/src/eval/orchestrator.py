"""orchestrator (D12): CLI driver for eval runs.

uv run python -m eval.run --stage smoke --benchmark widesearch --variants a1,a2

Flow (基准文档 §10):
1. load manifest (eval/manifests/widesearch_smoke.jsonl)
2. for each (case, variant, repetition): submit + poll + collect raw
3. normalize reports -> WideSearchResponse JSONL
4. all runs done -> start evaluator (D6 闸3, §10.2.6)
5. parse scores -> paired deltas -> summary
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass
class PairedDelta:
    instance_id: str
    metric: str
    a1_value: float | None
    a2_value: float | None
    delta: float | None
    a2_wins: bool | None  # True/False/None(null)


@dataclass
class RunManifest:
    stage: str
    benchmark: str
    repo_commit: str
    repo_dirty: bool
    benchmark_revision: str
    manifest_revision: str
    model: str
    provider: str
    base_url: str
    eval_model_config_name: str
    search_provider: str
    budget: dict[str, Any]
    variants: list[str]
    repetitions: int
    run_start: str = ""
    run_end: str = ""
    scorer_command: str = ""
    scorer_exit_code: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_id_for_stage(*, stage: str, benchmark: str, manifest_revision: str, short_sha: str) -> str:
    bench_short = "ws" if benchmark == "widesearch" else "drb2"
    return f"{stage}-{bench_short}-{manifest_revision[:7]}-{short_sha}"


def build_run_manifest(
    *,
    stage,
    benchmark,
    repo_commit,
    repo_dirty,
    benchmark_revision,
    manifest_revision,
    model,
    provider,
    base_url,
    eval_model_config_name,
    search_provider,
    budget,
    variants,
    repetitions,
) -> RunManifest:
    return RunManifest(
        stage=stage,
        benchmark=benchmark,
        repo_commit=repo_commit,
        repo_dirty=repo_dirty,
        benchmark_revision=benchmark_revision,
        manifest_revision=manifest_revision,
        model=model,
        provider=provider,
        base_url=base_url,
        eval_model_config_name=eval_model_config_name,
        search_provider=search_provider,
        budget=budget,
        variants=variants,
        repetitions=repetitions,
    )


def compute_paired_deltas(
    *,
    a1_rows: list,
    a2_rows: list,
    metric: str,
) -> list[PairedDelta]:
    """A2 - A1 per case (基准文档 §2.1). null (F6) -> delta None."""
    a1_by = {r.instance_id: r for r in a1_rows}
    a2_by = {r.instance_id: r for r in a2_rows}
    deltas: list[PairedDelta] = []
    for iid, a2 in a2_by.items():
        a1 = a1_by.get(iid)
        a1v = getattr(a1, metric) if a1 else None
        a2v = getattr(a2, metric)
        if a1v is None or a2v is None:
            deltas.append(PairedDelta(iid, metric, a1v, a2v, None, None))
            continue
        delta = a2v - a1v
        wins = bool(a2v > a1v) if abs(delta) > 1e-9 else None
        deltas.append(PairedDelta(iid, metric, a1v, a2v, delta, wins))
    return deltas


def _aggregate_operations(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """运行指标汇总（基准文档 §7.3）：按 variant 聚合 operations_rows。

    token/cost 是全量求和（每 case 独立计费），比率与耗时取均值。
    """

    def _per_variant(variant: str) -> dict[str, Any]:
        rs = [r for r in rows if r.get("variant") == variant]
        n = max(1, len(rs))
        return {
            "count": len(rs),
            "mean_search_calls": sum(r.get("search_calls", 0) for r in rs) / n,
            "mean_fetch_calls": sum(r.get("fetch_calls", 0) for r in rs) / n,
            "mean_tool_calls": sum(r.get("tool_calls_total", 0) for r in rs) / n,
            "mean_tool_success_rate": sum(r.get("tool_success_rate", 0.0) for r in rs) / n,
            "total_prompt_tokens": sum(r.get("prompt_tokens", 0) for r in rs),
            "total_completion_tokens": sum(r.get("completion_tokens", 0) for r in rs),
            "total_tokens": sum(r.get("total_tokens", 0) for r in rs),
            "total_cost": round(sum(r.get("cost", 0.0) for r in rs), 6),
            "mean_duration_seconds": round(
                sum(r.get("duration_seconds", 0.0) for r in rs) / n, 3
            ),
            "mean_distinct_domains": sum(r.get("distinct_domains", 0) for r in rs) / n,
            "mean_evidence_count": sum(r.get("evidence_count", 0) for r in rs) / n,
            "mean_fallback_count": sum(r.get("fallback_count", 0) for r in rs) / n,
        }

    return {v: _per_variant(v) for v in ("a1", "a2")}


def synthesize_missing_rows(
    *,
    cases: list,
    variants: list[str],
    existing_rows: list,
    projection_by_key: dict[tuple[str, str], dict[str, Any]],
    evaluator_failed_keys: set[tuple[str, str]],
    row_factory: Callable[[str, str, int, str | None, bool], Any],
) -> list:
    """Synthesize ScoreRows for cases the scorer didn't score (D13).

    For each (case, variant) missing from existing_rows:
    - F6 (evaluator_failed_keys) → ScoreRow all-None + failure_stage="evaluator" (null, not 0)
    - F1-F5 (terminal_status != completed, or completed but no scorer output)
      → ScoreRow all-0.0 + failure_stage from terminal_status (zero, in all-case denominator)

    ``row_factory(instance_id, variant, trial_idx, failure_stage, is_evaluator_failure)``
    builds the benchmark's ScoreRow (widesearch vs drb2 differ in fields).

    Returns the synthesized rows (existing_rows unchanged). Guarantees every
    (case, variant) has a row — no silent drop (基准文档 §8.3).
    """
    existing_keys = {(r.instance_id, r.variant) for r in existing_rows}
    synthesized: list[Any] = []
    stage_map = {
        "failed": "system_failed",
        "aborted": "timeout",
        "timeout": "timeout",
        "unknown": "no_output",
    }
    for case in cases:
        for variant in variants:
            variant_name = f"competitorlens_{variant}"
            key = (case.source_task_id, variant_name)
            if key in existing_keys:
                continue
            projection = projection_by_key.get(key, {})
            terminal = projection.get("status", "unknown")
            if key in evaluator_failed_keys:
                # F6: evaluator crashed, no score (null, separate count)
                synthesized.append(
                    row_factory(case.source_task_id, variant_name, 0, "evaluator", True)
                )
            else:
                # F1-F5: system failure → score 0 (in all-case denominator, 基准文档 §8.3)
                synthesized.append(
                    row_factory(
                        case.source_task_id, variant_name, 0,
                        stage_map.get(terminal, "no_output"), False,
                    )
                )
    return synthesized


def _widesearch_row_factory(
    instance_id: str, variant: str, trial_idx: int,
    failure_stage: str | None, is_evaluator_failure: bool,
) -> Any:
    from eval.evaluator.widesearch import ScoreRow

    if is_evaluator_failure:
        return ScoreRow(
            instance_id=instance_id, variant=variant, trial_idx=trial_idx,
            score=None, precision_by_item=None, recall_by_item=None, f1_by_item=None,
            precision_by_line=None, recall_by_line=None, f1_by_line=None,
            failure_stage=failure_stage,
        )
    return ScoreRow(
        instance_id=instance_id, variant=variant, trial_idx=trial_idx,
        score=0.0, precision_by_item=0.0, recall_by_item=0.0, f1_by_item=0.0,
        precision_by_line=0.0, recall_by_line=0.0, f1_by_line=0.0,
        failure_stage=failure_stage,
    )


def _drb2_row_factory(
    instance_id: str, variant: str, trial_idx: int,
    failure_stage: str | None, is_evaluator_failure: bool,
) -> Any:
    from eval.evaluator.drb2 import ScoreRow

    nulls = {"info_recall": None, "analysis": None, "presentation": None, "total": None}
    zeros = {"info_recall": 0.0, "analysis": 0.0, "presentation": 0.0, "total": 0.0}
    return ScoreRow(
        instance_id=instance_id, variant=variant, trial_idx=trial_idx,
        failure_stage=failure_stage, **(nulls if is_evaluator_failure else zeros),
    )


async def run_smoke(
    *,
    manifest_path: Path | str,
    variants: list[str],
    app_url: str = "http://127.0.0.1:8000",
    a1_url: str = "http://127.0.0.1:8001",
    out_root: Path | str = "data/evaluations",
    budget: dict[str, Any] | None = None,
    benchmark: str = "widesearch",
) -> str:
    """Full smoke run (基准文档 §10.2). Returns run_id.

    Integration: drives A2 (competitive_app) + A1 (single_agent service) over HTTP,
    normalizes reports, runs the benchmark evaluator (WideSearch table scorer or
    DRB II rubric judge), computes paired deltas + summary.

    ``benchmark`` ∈ {"widesearch", "drb2"}: selects raw/normalized/scores dir
    names + the evaluator. WideSearch = table F1 (official scorer); DRB II =
    rubric judge (info_recall/analysis/presentation proportions).
    """
    from eval.manifest import load_manifest
    from eval.runner.http_client import CompetitiveAppClient

    is_drb2 = benchmark == "drb2"
    raw_bench = "drb2" if is_drb2 else "widesearch"
    norm_dir_name = "drb2_reports" if is_drb2 else "widesearch_predictions"
    scores_raw_name = "drb2_raw" if is_drb2 else "widesearch_raw"
    scores_file_name = "drb2.jsonl" if is_drb2 else "widesearch.jsonl"
    # DRB II 打分侧数据集 (rubric gold): 仅 evaluator 读, runner 不碰 (gold 隔离)
    drb2_dataset = os.environ.get("DRB2_DATASET", "data/benchmarks/drb2/tasks_and_rubrics.jsonl")

    budget = budget or {"max_queries": 20, "max_fetches": 40, "max_wall_seconds": 720}
    cases = load_manifest(manifest_path)
    repo_sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode().strip()  # noqa: ASYNC221
    manifest_rev = (
        subprocess.check_output(  # noqa: ASYNC221
            ["git", "hash-object", str(manifest_path)]
        )
        .decode()
        .strip()[:7]
    )
    run_id = run_id_for_stage(
        stage="smoke", benchmark=benchmark, manifest_revision=manifest_rev, short_sha=repo_sha
    )
    run_dir = Path(out_root) / run_id
    (run_dir / "raw" / raw_bench).mkdir(parents=True, exist_ok=True)
    (run_dir / "normalized" / norm_dir_name).mkdir(parents=True, exist_ok=True)
    (run_dir / "scores").mkdir(parents=True, exist_ok=True)
    (run_dir / "summary").mkdir(parents=True, exist_ok=True)

    app_client = CompetitiveAppClient(base_url=app_url)
    import httpx

    projection_by_key: dict[tuple[str, str], dict[str, Any]] = {}

    for case in cases:
        for variant in variants:
            for rep in range(1):  # Smoke 1 repetition
                if variant == "a2":
                    # A2 per-task wall-clock guard must exceed the search wall
                    # budget + plan/write, else the harness aborts tasks mid-write
                    # (live: 720s search + ~40s plan + ~3min write > 900s guard
                    # → aborted empty reports). Derive from the search wall.
                    a2_timeout = int(budget.get("max_wall_seconds", 720)) + 900
                    result = await app_client.run_task(
                        research_brief=case.research_brief.model_dump(),
                        search_overrides={
                            "max_queries": budget["max_queries"],
                            "max_wall_seconds": budget["max_wall_seconds"],
                        },
                        timeout=a2_timeout,
                    )
                    markdown = result.report_markdown
                    socm = result.projection.get("coverage", {}) if result.projection else {}
                    task_id = result.task_id
                    terminal = result.terminal_status
                else:  # a1
                    async with httpx.AsyncClient(base_url=a1_url, timeout=900) as ac:
                        r = await ac.post(
                            "/eval/run",
                            json={
                                "research_brief": case.research_brief.model_dump(),
                                "search_overrides": budget,
                            },
                        )
                        task_id = r.json()["task_id"]
                        deadline = asyncio.get_event_loop().time() + 900
                        terminal = "running"
                        while asyncio.get_event_loop().time() < deadline:
                            s = await ac.get(f"/eval/run/{task_id}")
                            terminal = s.json().get("status", "running")
                            if terminal in ("completed", "failed", "aborted"):
                                break
                            await asyncio.sleep(5)
                        rep_r = await ac.get(f"/eval/run/{task_id}/report")
                        markdown = rep_r.json().get("markdown", "")
                        socm = None  # A1 no SOCM

                # write raw (基准文档 §10.2.3)
                raw_dir = run_dir / "raw" / raw_bench / case.case_id / variant / "0"
                raw_dir.mkdir(parents=True, exist_ok=True)
                projection = {"task_id": task_id, "status": terminal}
                projection_by_key[(case.source_task_id, f"competitorlens_{variant}")] = projection
                (raw_dir / "request.json").write_text(
                    case.model_dump_json() + "\n", encoding="utf-8"
                )
                (raw_dir / "task_projection.json").write_text(
                    json.dumps(projection) + "\n", encoding="utf-8"
                )
                (raw_dir / "report.md").write_text(markdown, encoding="utf-8")
                (raw_dir / "socm.json").write_text(
                    json.dumps(socm) if socm else f'{{"variant": "{variant}", "note": "no SOCM"}}',
                    encoding="utf-8",
                )

    # 2. normalize (基准文档 §10.2.4 / §10.2.5)
    for case in cases:
        for variant in variants:
            md = (
                run_dir / "raw" / raw_bench / case.case_id / variant / "0" / "report.md"
            ).read_text(encoding="utf-8")
            norm_prefix = f"competitorlens_{variant}_{case.source_task_id}_0"
            if is_drb2:
                # DRB II: 只做编码/文件名规范化 (写 .md)
                from eval.normalizer.drb2 import normalize_report as drb2_normalize

                drb2_normalize(
                    report_md=md,
                    instance_id=case.source_task_id,
                    model_config_name=f"competitorlens_{variant}",
                    trial_idx=0,
                    out_path=run_dir / "normalized" / norm_dir_name / f"{norm_prefix}.md",
                )
            else:
                from eval.normalizer.widesearch import normalize_report

                normalize_report(
                    report_md=md,
                    required_headers=case.research_brief.dimensions,
                    instance_id=case.source_task_id,
                    model_config_name=f"competitorlens_{variant}",
                    trial_idx=0,
                    out_path=(
                        run_dir
                        / "normalized"
                        / norm_dir_name
                        / f"{norm_prefix}_response.jsonl"
                    ),
                )

    # 2.5 operations (基准文档 §12.5: 三源汇总)
    from eval.operations.collector import collect_operations

    operations_rows: list[dict[str, Any]] = []
    for case in cases:
        for variant in variants:
            raw_dir = run_dir / "raw" / raw_bench / case.case_id / variant / "0"
            projection_file = raw_dir / "task_projection.json"
            projection = {}
            if projection_file.is_file():
                projection = json.loads(projection_file.read_text(encoding="utf-8"))
            socm_file = raw_dir / "socm.json"
            socm = None
            if socm_file.is_file():
                socm_obj = json.loads(socm_file.read_text(encoding="utf-8"))
                if isinstance(socm_obj, dict) and "filled" not in socm_obj:
                    socm = None  # A1 placeholder, no real SOCM
                else:
                    socm = socm_obj
            # events.jsonl: A2 only (competitive_app writes data/runs/<task_id>/)
            events_path = Path(f"data/runs/{projection.get('task_id', '')}/events.jsonl")
            ops = collect_operations(events_path=events_path, projection=projection, socm=socm)
            ops_dict = ops.to_dict()
            ops_dict["case_id"] = case.case_id
            ops_dict["variant"] = variant
            ops_dict["repetition"] = 0
            operations_rows.append(ops_dict)
            (raw_dir / "operations.json").write_text(
                json.dumps(ops_dict, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    (run_dir / "scores" / "operations.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in operations_rows) + "\n",
        encoding="utf-8",
    )

    # 3. evaluator (基准文档 §10.3, all runs done first §10.2.6)
    all_rows = []
    last_cmd = ""
    last_rc = 0
    evaluator_failed_keys: set[tuple[str, str]] = set()
    for variant in variants:
        variant_name = f"competitorlens_{variant}"
        if is_drb2:
            # DRB II: rubric judge (in-process; rubric gold 只在此读取)
            from eval.evaluator.drb2 import run_drb2_evaluation

            # DRB2_MAX_ITEMS env: smoke 限速 (每维度最多 judge 条数; 0/缺省 = 全部)
            max_items = int(os.environ.get("DRB2_MAX_ITEMS", "0") or 0) or None
            # reports 以 trial 0 落盘 (normalize trial_idx=0); evaluator 按 0 读回
            rows = await run_drb2_evaluation(
                response_root=run_dir / "normalized" / norm_dir_name,
                result_save_root=run_dir / "scores" / scores_raw_name,
                dataset_path=drb2_dataset,
                model_config_name=variant_name,
                trial_num=0,
                max_items=max_items,
            )
            rc = 0
            scored_ids = {r.instance_id for r in rows}
            for case in cases:
                if case.source_task_id not in scored_ids:
                    evaluator_failed_keys.add((case.source_task_id, variant_name))
        else:
            from eval.evaluator.widesearch import build_scorer_command, parse_scores, run_scorer

            cmd = build_scorer_command(
                model_config_name=variant_name,
                eval_model_config_name="deepseek-v3.2",
                response_root=str(run_dir / "normalized" / norm_dir_name),
                result_save_root=str(run_dir / "scores" / scores_raw_name),
                trial_num=1,
            )
            rc = run_scorer(cmd)
            rows = parse_scores(
                raw_dir=run_dir / "scores" / scores_raw_name,
                model_config_name=variant_name,
                trial_num=1,
            )
            # F6: scorer crashed (rc != 0) AND a case has no output file → evaluator failure
            if rc != 0:
                scored_ids = {r.instance_id for r in rows}
                for case in cases:
                    if case.source_task_id not in scored_ids:
                        evaluator_failed_keys.add((case.source_task_id, variant_name))
        all_rows.extend(rows)
        last_rc = rc

    # D13 §14.2-14.3: synthesize rows for unscored cases (F1-F5 → 0, F6 → null)
    all_rows.extend(
        synthesize_missing_rows(
            cases=cases,
            variants=variants,
            existing_rows=all_rows,
            projection_by_key=projection_by_key,
            evaluator_failed_keys=evaluator_failed_keys,
            row_factory=_drb2_row_factory if is_drb2 else _widesearch_row_factory,
        )
    )

    # 4. paired deltas + summary (基准文档 §10.4)
    a1_rows = [r for r in all_rows if r.variant == "competitorlens_a1"]
    a2_rows = [r for r in all_rows if r.variant == "competitorlens_a2"]
    delta_metric = "total" if is_drb2 else "f1_by_item"
    deltas = compute_paired_deltas(a1_rows=a1_rows, a2_rows=a2_rows, metric=delta_metric)

    (run_dir / "scores" / "paired_deltas.json").write_text(
        json.dumps([asdict(d) for d in deltas], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "scores" / scores_file_name).write_text(
        "\n".join(json.dumps(asdict(r), ensure_ascii=False) for r in all_rows) + "\n",
        encoding="utf-8",
    )

    # summary (mean@1, 基准文档 §12.3; D13 失败口径 §14.3)
    deltas_valid = [d.delta for d in deltas if d.delta is not None]
    # completed = 被测系统跑完 (failure_stage None) 且 evaluator 出分 (排除 F6 evaluator)
    completed = [r for r in all_rows if r.failure_stage is None]
    evaluator_failures = len([r for r in all_rows if r.failure_stage == "evaluator"])
    summary: dict[str, Any] = {
        "repetitions": 1,
        "all_case_count": len(all_rows),
        "completed_count": len(completed),
        "evaluator_failures": evaluator_failures,  # F6: null, not 0 (基准文档 §14.2)
        "paired_delta_mean": sum(deltas_valid) / max(1, len(deltas_valid)),
        "operations": _aggregate_operations(operations_rows),
    }
    if is_drb2:
        a1_valid = [r.total for r in a1_rows if r.total is not None]
        a2_valid = [r.total for r in a2_rows if r.total is not None]
        summary["mean_total_a1"] = sum(a1_valid) / max(1, len(a1_valid))
        summary["mean_total_a2"] = sum(a2_valid) / max(1, len(a2_valid))
        for dim in ("info_recall", "analysis", "presentation"):
            summary[f"mean_{dim}_a2"] = sum(
                getattr(r, dim, 0.0) or 0.0 for r in a2_rows if r.failure_stage is None
            ) / max(1, len([r for r in a2_rows if r.failure_stage is None]))
    else:
        a1_valid = [r.f1_by_item for r in a1_rows if r.f1_by_item is not None]
        a2_valid = [r.f1_by_item for r in a2_rows if r.f1_by_item is not None]
        summary["mean_f1_a1"] = sum(a1_valid) / max(1, len(a1_valid))
        summary["mean_f1_a2"] = sum(a2_valid) / max(1, len(a2_valid))
    (run_dir / "summary" / "metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # manifest (基准文档 §12.7)
    manifest = build_run_manifest(
        stage="smoke",
        benchmark=benchmark,
        repo_commit=repo_sha,
        repo_dirty=bool(subprocess.check_output(["git", "status", "--porcelain"]).decode().strip()),  # noqa: ASYNC221
        benchmark_revision=_read_drb2_revision() if is_drb2 else _read_ws_sha(),
        manifest_revision=manifest_rev,
        model="deepseek-v3.2",
        provider="openai",
        base_url=os.environ.get("OPENAI_BASE_URL", ""),
        eval_model_config_name="deepseek-v3.2",
        search_provider="tavily",
        budget=budget,
        variants=variants,
        repetitions=1,
    )
    manifest.scorer_command = last_cmd
    manifest.scorer_exit_code = last_rc
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # D11 §9 剩余产物
    # cases.jsonl — 运行时 manifest 拷贝
    (run_dir / "cases.jsonl").write_text(
        "\n".join(c.model_dump_json() for c in cases) + "\n", encoding="utf-8"
    )
    # summary/metrics.csv — 表格版
    import csv
    from io import StringIO

    score_col = "total" if is_drb2 else "f1_by_item"
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(["instance_id", "variant", score_col, "failure_stage"])
    for r in sorted(all_rows, key=lambda x: (x.instance_id, x.variant)):
        val = getattr(r, score_col, None)
        writer.writerow([r.instance_id, r.variant, val if val is not None else "", r.failure_stage or ""])
    (run_dir / "summary" / "metrics.csv").write_text(si.getvalue(), encoding="utf-8")
    # summary/report.md — 人读
    mean_key_a1 = "mean_total_a1" if is_drb2 else "mean_f1_a1"
    mean_key_a2 = "mean_total_a2" if is_drb2 else "mean_f1_a2"
    report_md = (
        f"# Eval Smoke Run {run_id}\n\n"
        f"- benchmark: {benchmark}\n"
        f"- all_case_count: {summary['all_case_count']}\n"
        f"- completed_count: {summary['completed_count']}\n"
        f"- evaluator_failures (F6): {summary['evaluator_failures']}\n"
        f"- mean_{score_col}_a1: {summary.get(mean_key_a1, 0.0):.4f}\n"
        f"- mean_{score_col}_a2: {summary.get(mean_key_a2, 0.0):.4f}\n"
        f"- paired_delta_mean: {summary['paired_delta_mean']:.4f}\n\n"
        f"## Per-case scores\n\n"
    )
    report_md += f"| instance_id | variant | {score_col} | failure_stage |\n"
    report_md += "|---|---|---|---|\n"
    for r in sorted(all_rows, key=lambda x: (x.instance_id, x.variant)):
        val = getattr(r, score_col, None)
        v = f"{val:.4f}" if val is not None else "null"
        report_md += f"| {r.instance_id} | {r.variant} | {v} | {r.failure_stage or ''} |\n"
    (run_dir / "summary" / "report.md").write_text(report_md, encoding="utf-8")

    return run_id


def _read_ws_sha() -> str:
    """Read WideSearch repo SHA from REVISION.txt or WS_REPO_SHA.txt."""
    for p in (
        "data/benchmarks/widesearch/WS_REPO_SHA.txt",
        "data/benchmarks/widesearch/REVISION.txt",
    ):
        try:
            text = Path(p).read_text(encoding="utf-8").strip()
            if "SHA:" in text:
                for line in text.splitlines():
                    if "repo SHA" in line:
                        return line.split(":", 1)[1].strip()
            return text.splitlines()[0] if text else ""
        except FileNotFoundError:
            continue
    return ""


def _read_drb2_revision() -> str:
    """Read DRB II dataset revision from REVISION.txt (tracked)."""
    try:
        return Path("data/benchmarks/drb2/REVISION.txt").read_text(
            encoding="utf-8"
        ).strip()
    except FileNotFoundError:
        return "imlrz/DeepResearch-Bench-II@main"


__all__ = [
    "PairedDelta",
    "RunManifest",
    "build_run_manifest",
    "compute_paired_deltas",
    "run_id_for_stage",
    "run_smoke",
]
