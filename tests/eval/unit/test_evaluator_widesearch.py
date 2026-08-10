"""WideSearch evaluator: call官方 scorer + parse scores (D10 H1)."""

from __future__ import annotations

import json
from pathlib import Path

from eval.evaluator.widesearch import build_scorer_command, parse_scores


def test_build_command_includes_env_and_paths():
    cmd = build_scorer_command(
        model_config_name="competitorlens_a2",
        eval_model_config_name="deepseek-v4-flash",
        response_root="data/evaluations/run1/normalized/widesearch_predictions",
        result_save_root="data/evaluations/run1/scores/widesearch_raw",
        trial_num=1,
    )
    assert "run_infer_and_eval_batching.py" in cmd
    assert "--stage=eval" in cmd
    assert "competitorlens_a2" in cmd
    assert "deepseek-v4-flash" in cmd
    assert "HF_HUB_OFFLINE=1" in cmd
    assert "HF_DATASETS_CACHE=data/benchmarks/hf_cache" in cmd


def test_parse_scores_reads_eval_result_json(tmp_path: Path):
    # 模拟官方 scorer 输出的 eval_result.json
    raw = tmp_path / "competitorlens_a2_ws_en_001_0_eval_result.json"
    raw.write_text(
        json.dumps(
            {
                "score": 0.85,
                "precision_by_item": 0.9,
                "recall_by_item": 0.8,
                "f1_by_item": 0.85,
                "precision_by_line": 0.88,
                "recall_by_line": 0.82,
                "f1_by_line": 0.85,
            }
        )
    )
    rows = parse_scores(raw_dir=tmp_path, model_config_name="competitorlens_a2", trial_num=1)
    assert len(rows) == 1
    assert rows[0].instance_id == "ws_en_001"
    assert rows[0].f1_by_item == 0.85
    assert rows[0].score == 0.85


def test_parse_scores_missing_file_returns_null(tmp_path: Path):
    rows = parse_scores(raw_dir=tmp_path, model_config_name="competitorlens_a2", trial_num=1)
    assert len(rows) == 0  # no files -> no rows; orchestrator treats missing as F6 null
