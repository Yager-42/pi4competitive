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
from typing import Any


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


async def run_smoke(
    *,
    manifest_path: Path | str,
    variants: list[str],
    app_url: str = "http://127.0.0.1:8000",
    a1_url: str = "http://127.0.0.1:8001",
    out_root: Path | str = "data/evaluations",
    budget: dict[str, Any] | None = None,
) -> str:
    """Full smoke run (基准文档 §10.2). Returns run_id.

    Integration: drives A2 (competitive_app) + A1 (single_agent service) over HTTP,
    normalizes reports, runs evaluator, computes paired deltas + summary.
    """
    from eval.evaluator.widesearch import build_scorer_command, parse_scores, run_scorer
    from eval.manifest import load_manifest
    from eval.normalizer.widesearch import normalize_report
    from eval.runner.http_client import CompetitiveAppClient

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
        stage="smoke", benchmark="widesearch", manifest_revision=manifest_rev, short_sha=repo_sha
    )
    run_dir = Path(out_root) / run_id
    (run_dir / "raw" / "widesearch").mkdir(parents=True, exist_ok=True)
    (run_dir / "normalized" / "widesearch_predictions").mkdir(parents=True, exist_ok=True)
    (run_dir / "scores").mkdir(parents=True, exist_ok=True)
    (run_dir / "summary").mkdir(parents=True, exist_ok=True)

    app_client = CompetitiveAppClient(base_url=app_url)
    import httpx

    for case in cases:
        for variant in variants:
            for rep in range(1):  # Smoke 1 repetition
                if variant == "a2":
                    result = await app_client.run_task(
                        research_brief=case.research_brief.model_dump(),
                        search_overrides={
                            "max_queries": budget["max_queries"],
                            "max_wall_seconds": budget["max_wall_seconds"],
                        },
                        timeout=900,
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
                raw_dir = run_dir / "raw" / "widesearch" / case.case_id / variant / "0"
                raw_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / "request.json").write_text(
                    case.model_dump_json() + "\n", encoding="utf-8"
                )
                (raw_dir / "task_projection.json").write_text(
                    json.dumps({"task_id": task_id, "status": terminal}) + "\n", encoding="utf-8"
                )
                (raw_dir / "report.md").write_text(markdown, encoding="utf-8")
                (raw_dir / "socm.json").write_text(
                    json.dumps(socm) if socm else f'{{"variant": "{variant}", "note": "no SOCM"}}',
                    encoding="utf-8",
                )

    # 2. normalize (基准文档 §10.2.4)
    for case in cases:
        for variant in variants:
            md = (
                run_dir / "raw" / "widesearch" / case.case_id / variant / "0" / "report.md"
            ).read_text(encoding="utf-8")
            out = (
                run_dir
                / "normalized"
                / "widesearch_predictions"
                / f"competitorlens_{variant}_{case.source_task_id}_0_response.jsonl"
            )
            normalize_report(
                report_md=md,
                required_headers=case.research_brief.dimensions,
                instance_id=case.source_task_id,
                model_config_name=f"competitorlens_{variant}",
                trial_idx=0,
                out_path=out,
            )

    # 3. evaluator (基准文档 §10.3, all runs done first §10.2.6)
    all_rows = []
    last_cmd = ""
    last_rc = 0
    for variant in variants:
        cmd = build_scorer_command(
            model_config_name=f"competitorlens_{variant}",
            eval_model_config_name="deepseek-v4-flash",
            response_root=str(run_dir / "normalized" / "widesearch_predictions"),
            result_save_root=str(run_dir / "scores" / "widesearch_raw"),
            trial_num=1,
        )
        rc = run_scorer(cmd)
        rows = parse_scores(
            raw_dir=run_dir / "scores" / "widesearch_raw",
            model_config_name=f"competitorlens_{variant}",
            trial_num=1,
        )
        all_rows.extend(rows)
        last_cmd = cmd
        last_rc = rc

    # 4. paired deltas + summary (基准文档 §10.4)
    a1_rows = [r for r in all_rows if r.variant == "competitorlens_a1"]
    a2_rows = [r for r in all_rows if r.variant == "competitorlens_a2"]
    deltas = compute_paired_deltas(a1_rows=a1_rows, a2_rows=a2_rows, metric="f1_by_item")

    (run_dir / "scores" / "paired_deltas.json").write_text(
        json.dumps([asdict(d) for d in deltas], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "scores" / "widesearch.jsonl").write_text(
        "\n".join(json.dumps(asdict(r), ensure_ascii=False) for r in all_rows) + "\n",
        encoding="utf-8",
    )

    # summary (mean@1, 基准文档 §12.3)
    a1_valid = [r.f1_by_item for r in a1_rows if r.f1_by_item is not None]
    a2_valid = [r.f1_by_item for r in a2_rows if r.f1_by_item is not None]
    deltas_valid = [d.delta for d in deltas if d.delta is not None]
    summary = {
        "repetitions": 1,
        "all_case_count": len(all_rows),
        "completed_count": len([r for r in all_rows if r.failure_stage is None]),
        "mean_f1_a1": sum(a1_valid) / max(1, len(a1_valid)),
        "mean_f1_a2": sum(a2_valid) / max(1, len(a2_valid)),
        "paired_delta_mean": sum(deltas_valid) / max(1, len(deltas_valid)),
    }
    (run_dir / "summary" / "metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # manifest (基准文档 §12.7)
    manifest = build_run_manifest(
        stage="smoke",
        benchmark="widesearch",
        repo_commit=repo_sha,
        repo_dirty=bool(subprocess.check_output(["git", "status", "--porcelain"]).decode().strip()),  # noqa: ASYNC221
        benchmark_revision=_read_ws_sha(),
        manifest_revision=manifest_rev,
        model="deepseek-v4-flash",
        provider="openai",
        base_url=os.environ.get("OPENAI_BASE_URL", ""),
        eval_model_config_name="deepseek-v4-flash",
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


__all__ = [
    "PairedDelta",
    "RunManifest",
    "build_run_manifest",
    "compute_paired_deltas",
    "run_id_for_stage",
    "run_smoke",
]
