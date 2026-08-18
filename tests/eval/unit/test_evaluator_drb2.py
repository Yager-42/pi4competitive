"""DRB II evaluator: rubric LLM-judge (D1 C2-wide, 打分侧).

Run scoring offline with an injected ``judge_fn``; verify dimension
proportions + total + file outputs. Gold isolation: 打分侧允许引用
rubric / 打分内容.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.evaluator.drb2 import (
    _dimension_score,
    _judge_prompt,
    _parse_judge_json,
    load_task_dataset,
    parse_scores,
    run_drb2_evaluation,
)


def _dataset(tmp_path: Path, *, with_extra: bool = True) -> Path:
    p = tmp_path / "tasks_and_rubrics.jsonl"
    rows = [
        {
            "id": "task10",
            "idx": 22,
            "prompt": "Research the life cycle cost of EVs.",
            "content": {
                "rubric": {
                    "info_recall": ["states the 2019 EV battery cost", "lists a policy"],
                    "analysis": ["explains a cost trend"],
                    "presentation": ["uses a table"],
                }
            },
        }
    ]
    if with_extra:
        rows.append(
            {
                "id": "task4",
                "idx": 4,
                "prompt": "Report on retirement savings gaps.",
                "content": {"rubric": {"info_recall": ["names a country"], "analysis": []}},
            }
        )
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def test_load_task_dataset_keys(tmp_path: Path):
    tasks = load_task_dataset(_dataset(tmp_path))
    assert "drb2_22" in tasks
    assert set(tasks["drb2_22"]["rubric"]) == {"info_recall", "analysis", "presentation"}
    assert len(tasks["drb2_22"]["rubric"]["info_recall"]) == 2


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"score": 1, "reason": "r", "evidence": "e"}', 1),
        ('{"score": -1}', -1),
        ('{"score": 0}', 0),
        ("```json\n{\"score\": 1}\n```", 1),
        ('garbage "score": 1 somewhere', 1),
        ("not json at all", None),
    ],
)
def test_parse_judge_json(text: str, expected):
    assert _parse_judge_json(text) == expected


def test_dimension_score_proportion():
    assert _dimension_score([1, 1, 0]) == pytest.approx(2 / 3)
    assert _dimension_score([]) == 0.0
    assert _dimension_score([-1, 0, 0]) == 0.0


def test_judge_prompt_contains_task_item_and_blocked_note():
    task = {"prompt": "Task text **important** blocked: url"}
    prompt = _judge_prompt(task, "some rubric item", "# report")
    assert "Task text" in prompt
    assert "some rubric item" in prompt
    assert "BLOCKED" in prompt
    assert "# report" in prompt


@pytest.mark.asyncio
async def test_run_drb2_evaluation_scores_dimensions(tmp_path: Path):
    async def judge_fn(prompt: str) -> str:
        if "explains a cost trend" in prompt:  # analysis item
            return '{"score": 1, "reason": "ok", "evidence": "x"}'
        return '{"score": 0, "reason": "not mentioned", "evidence": ""}'

    response_root = tmp_path / "reports"
    response_root.mkdir()
    (response_root / "competitorlens_a2_drb2_22_0.md").write_text("# EV report", encoding="utf-8")

    rows = await run_drb2_evaluation(
        response_root=response_root,
        result_save_root=tmp_path / "raw",
        dataset_path=_dataset(tmp_path),
        model_config_name="competitorlens_a2",
        trial_num=0,
        judge_fn=judge_fn,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.instance_id == "drb2_22"
    assert row.variant == "competitorlens_a2"
    # info_recall 2 items: "states the 2019..." (judge returns 0) + "lists a policy" (0) → 0.0
    assert row.info_recall == 0.0
    # analysis 1 item → 1/1
    assert row.analysis == pytest.approx(1.0)
    # presentation 1 item → 0/1
    assert row.presentation == 0.0
    # total = mean(0.0, 1.0, 0.0)
    assert row.total == pytest.approx(1 / 3)
    assert row.failure_stage is None
    # result JSON written
    result_files = list((tmp_path / "raw").glob("*_eval_result.json"))
    assert len(result_files) == 1


@pytest.mark.asyncio
async def test_run_drb2_evaluation_missing_task_marks_failure(tmp_path: Path):
    async def judge_fn(prompt: str) -> str:
        return '{"score": 1}'

    response_root = tmp_path / "reports"
    response_root.mkdir()
    (response_root / "competitorlens_a2_drb2_999_0.md").write_text("x", encoding="utf-8")

    rows = await run_drb2_evaluation(
        response_root=response_root,
        result_save_root=tmp_path / "raw",
        dataset_path=_dataset(tmp_path),
        model_config_name="competitorlens_a2",
        trial_num=0,
        judge_fn=judge_fn,
    )
    assert rows[0].failure_stage == "missing_task"
    assert rows[0].total is None


def test_parse_scores_round_trip(tmp_path: Path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "competitorlens_a2_drb2_22_0_eval_result.json").write_text(
        json.dumps(
            {
                "instance_id": "drb2_22", "variant": "competitorlens_a2", "trial_idx": 0,
                "info_recall": 0.5, "analysis": 1.0, "presentation": 0.25, "total": 0.583,
            }
        ),
        encoding="utf-8",
    )
    rows = parse_scores(raw_dir=raw, model_config_name="competitorlens_a2", trial_num=0)
    assert len(rows) == 1
    assert rows[0].instance_id == "drb2_22"
    assert rows[0].total == pytest.approx(0.583)
