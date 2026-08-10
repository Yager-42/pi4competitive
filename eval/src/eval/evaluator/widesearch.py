"""WideSearch evaluator (D10 H1).

调官方 scorer (vendor/widesearch/scripts/run_infer_and_eval_batching.py
--stage=eval), 走 HF cache 离线, 不改官方代码 (patch config.py 在 vendor/).
parse eval_result.json -> ScoreRow.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ScoreRow:
    instance_id: str
    variant: str
    trial_idx: int
    score: float | None
    precision_by_item: float | None
    recall_by_item: float | None
    f1_by_item: float | None
    precision_by_line: float | None
    recall_by_line: float | None
    f1_by_line: float | None
    failure_stage: str | None = None


def build_scorer_command(
    *,
    model_config_name: str,
    eval_model_config_name: str,
    response_root: str,
    result_save_root: str,
    trial_num: int,
    scorer_script: str = "vendor/widesearch/scripts/run_infer_and_eval_batching.py",
) -> str:
    """构造官方 scorer 命令串 (原样进 run manifest, 基准文档 §10.3)."""
    return (
        f"HF_DATASETS_CACHE=data/benchmarks/hf_cache "
        f"HF_HUB_OFFLINE=1 "
        f"python3 {scorer_script} "
        f"--trial_num={trial_num} "
        f"--model_config_name={model_config_name} "
        f"--eval_model_config_name={eval_model_config_name} "
        f"--response_root={response_root} "
        f"--result_save_root={result_save_root} "
        f"--stage=eval"
    )


def run_scorer(command: str) -> int:
    """Run scorer subprocess, return exit code."""
    result = subprocess.run(command, shell=True, capture_output=True, text=True, check=False)
    return result.returncode


def parse_scores(*, raw_dir: Path | str, model_config_name: str, trial_num: int) -> list[ScoreRow]:
    """读 {model_config_name}_{instance_id}_{trial_idx}_eval_result.json."""
    raw = Path(raw_dir)
    rows: list[ScoreRow] = []
    if not raw.is_dir():
        return rows
    for f in sorted(raw.glob(f"{model_config_name}_*_eval_result.json")):
        # filename: competitorlens_a2_ws_en_001_0_eval_result.json
        name = f.stem  # competitorlens_a2_ws_en_001_0_eval_result
        # strip the trailing _eval_result suffix produced by glob
        name = name.removesuffix("_eval_result")
        # name is now: competitorlens_a2_ws_en_001_0
        parts = name.split("_")
        # variant = parts[0..1] = competitorlens a2; instance_id = middle; trial = last
        # WideSearch instance_id 格式 ws_en_001 / ws_zh_001
        # 保守: 找 "ws" 开头
        try:
            ws_idx = parts.index("ws") if "ws" in parts else 0
            instance_id = "_".join(parts[ws_idx:-1])  # ws_en_001
            trial_idx = int(parts[-1])
        except (ValueError, IndexError):
            continue
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            rows.append(
                ScoreRow(
                    instance_id,
                    model_config_name,
                    trial_idx,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    "evaluator_parse_error",
                )
            )
            continue
        rows.append(
            ScoreRow(
                instance_id=instance_id,
                variant=model_config_name,
                trial_idx=trial_idx,
                score=obj.get("score"),
                precision_by_item=obj.get("precision_by_item"),
                recall_by_item=obj.get("recall_by_item"),
                f1_by_item=obj.get("f1_by_item"),
                precision_by_line=obj.get("precision_by_line"),
                recall_by_line=obj.get("recall_by_line"),
                f1_by_line=obj.get("f1_by_line"),
            )
        )
    return rows


__all__ = ["ScoreRow", "build_scorer_command", "parse_scores", "run_scorer"]
