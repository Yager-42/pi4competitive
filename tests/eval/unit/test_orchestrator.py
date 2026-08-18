"""orchestrator: CLI driver + run manifest + paired delta (D12)."""

from __future__ import annotations

from eval.orchestrator import (
    _widesearch_row_factory,
    build_run_manifest,
    compute_paired_deltas,
    run_id_for_stage,
    synthesize_missing_rows,
)


def test_run_id_format():
    rid = run_id_for_stage(
        stage="smoke", benchmark="widesearch", manifest_revision="abc123", short_sha="a80dab2"
    )
    assert rid == "smoke-ws-abc123-a80dab2"


def test_build_run_manifest_captures_pins():
    m = build_run_manifest(
        stage="smoke",
        benchmark="widesearch",
        repo_commit="a80dab2",
        repo_dirty=False,
        benchmark_revision="wsha1",
        manifest_revision="mrev1",
        model="deepseek-v4-flash",
        provider="openai",
        base_url="https://api.chatanywhere.tech",
        eval_model_config_name="deepseek-v4-flash",
        search_provider="tavily",
        budget={"max_queries": 20, "max_fetches": 40, "max_wall_seconds": 720},
        variants=["a1", "a2"],
        repetitions=1,
    )
    assert m.repo_commit == "a80dab2"
    assert m.model == "deepseek-v4-flash"
    assert m.budget["max_queries"] == 20
    assert m.variants == ["a1", "a2"]
    d = m.to_dict()
    assert d["repo_dirty"] is False


def test_compute_paired_deltas():
    from eval.evaluator.widesearch import ScoreRow

    a1 = [
        ScoreRow("ws_en_001", "competitorlens_a1", 0, 0.5, 0.6, 0.4, 0.5, 0.6, 0.4, 0.5, None),
        ScoreRow("ws_en_002", "competitorlens_a1", 0, 0.3, 0.4, 0.35, 0.35, 0.4, 0.35, 0.3, None),
    ]
    a2 = [
        ScoreRow("ws_en_001", "competitorlens_a2", 0, 0.8, 0.9, 0.85, 0.85, 0.9, 0.85, 0.8, None),
        ScoreRow("ws_en_002", "competitorlens_a2", 0, 0.2, 0.3, 0.25, 0.25, 0.3, 0.25, 0.2, None),
    ]
    deltas = compute_paired_deltas(a1_rows=a1, a2_rows=a2, metric="f1_by_item")
    assert len(deltas) == 2
    assert deltas[0].instance_id == "ws_en_001"
    assert abs(deltas[0].delta - (0.85 - 0.5)) < 1e-9
    assert deltas[0].a2_wins is True
    assert deltas[1].a2_wins is False  # 0.25 < 0.35


def test_compute_paired_deltas_handles_null_a2():
    from eval.evaluator.widesearch import ScoreRow

    a1 = [
        ScoreRow("ws_en_001", "competitorlens_a1", 0, 0.5, None, None, 0.5, None, None, 0.5, None)
    ]
    a2 = [
        ScoreRow(
            "ws_en_001", "competitorlens_a2", 0, None, None, None, None, None, None, None, "F6"
        )
    ]
    deltas = compute_paired_deltas(a1_rows=a1, a2_rows=a2, metric="f1_by_item")
    assert deltas[0].a2_wins is None  # null -> no comparison
    assert deltas[0].delta is None


def test_synthesize_missing_rows_zero_for_system_failure():
    """D13 §14.2: F1-F5 (terminal != completed) → score 0, in all-case denominator."""
    from dataclasses import dataclass

    @dataclass
    class _Case:
        source_task_id: str

    cases = [_Case("ws_en_001"), _Case("ws_en_002")]
    variants = ["a2"]
    existing = []  # scorer produced nothing for either
    projection_by_key = {
        ("ws_en_001", "competitorlens_a2"): {"status": "failed"},  # F1-F5
        ("ws_en_002", "competitorlens_a2"): {"status": "aborted"},  # F1 timeout
    }
    evaluator_failed_keys = set()  # no F6
    synthesized = synthesize_missing_rows(
        cases=cases,
        variants=variants,
        existing_rows=existing,
        projection_by_key=projection_by_key,
        evaluator_failed_keys=evaluator_failed_keys,
        row_factory=_widesearch_row_factory,
    )
    assert len(synthesized) == 2
    for r in synthesized:
        assert r.score == 0.0
        assert r.f1_by_item == 0.0
        assert r.failure_stage in ("system_failed", "timeout")
        assert r.failure_stage != "evaluator"


def test_synthesize_missing_rows_null_for_evaluator_crash():
    """D13 §14.2: F6 (evaluator crash) → null, not 0; separate count."""
    from dataclasses import dataclass

    @dataclass
    class _Case:
        source_task_id: str

    cases = [_Case("ws_en_001")]
    variants = ["a2"]
    existing = []
    projection_by_key = {("ws_en_001", "competitorlens_a2"): {"status": "completed"}}
    evaluator_failed_keys = {("ws_en_001", "competitorlens_a2")}  # scorer crashed
    synthesized = synthesize_missing_rows(
        cases=cases,
        variants=variants,
        existing_rows=existing,
        projection_by_key=projection_by_key,
        evaluator_failed_keys=evaluator_failed_keys,
        row_factory=_widesearch_row_factory,
    )
    assert len(synthesized) == 1
    assert synthesized[0].score is None
    assert synthesized[0].f1_by_item is None
    assert synthesized[0].failure_stage == "evaluator"


def test_synthesize_missing_rows_skips_existing():
    """Cases already scored by scorer are not re-synthesized."""
    from dataclasses import dataclass

    from eval.evaluator.widesearch import ScoreRow

    @dataclass
    class _Case:
        source_task_id: str

    cases = [_Case("ws_en_001"), _Case("ws_en_002")]
    variants = ["a2"]
    existing = [
        ScoreRow("ws_en_001", "competitorlens_a2", 0, 0.8, 0.9, 0.85, 0.8, 0.9, 0.85, 0.8, None)
    ]
    projection_by_key = {
        ("ws_en_001", "competitorlens_a2"): {"status": "completed"},
        ("ws_en_002", "competitorlens_a2"): {"status": "failed"},
    }
    synthesized = synthesize_missing_rows(
        cases=cases,
        variants=variants,
        existing_rows=existing,
        projection_by_key=projection_by_key,
        evaluator_failed_keys=set(),
        row_factory=_widesearch_row_factory,
    )
    assert len(synthesized) == 1  # only ws_en_002 missing
    assert synthesized[0].instance_id == "ws_en_002"
    assert synthesized[0].score == 0.0
