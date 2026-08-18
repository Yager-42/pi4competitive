"""DRB II evaluator — rubric LLM-judge (D1 C2-wide).

DeepResearch Bench II (DRB2) 官方打分方法：把任务 + 每一条二元 rubric 序列化，
LLM judge 对报告给出 ``score ∈ {1, 0, -1}``（1 = 有证据满足；0 = 未提及；
-1 = 提及但证据依赖被禁引用），再加 reason + evidence。三维度得分 = 各维度
通过比例；总分 = 三维度均值（imlrz/DeepResearch-Bench-II, arXiv:2601.08536）。

本模块是打分侧进程（gold 隔离契约允许引用 rubric / 打分内容），由 orchestrator
在归一化后调用。judge 默认走 pi_ai（env OPENAI_MODEL/BASE_URL/KEY，同 A1），
可注入 ``judge_fn`` 便于离线单测。

Gold 隔离：evaluator 不在 runner 进程路径 (adapter/normalizer/runner)，可引用
``tasks_and_rubrics`` / ``rubric``；运行进程不得读该数据集。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Awaitable, Callable

_DIMENSIONS = ("info_recall", "analysis", "presentation")
_JUDGE_OUTPUT_TOKEN_CAP = 1024
# 单条 judge 调用的超时: 网关偶发挂起, 不设超时会阻塞整个打分 (live 实测 7min 卡死)
_JUDGE_CALL_TIMEOUT_S = 60.0

JudgeFn = Callable[[str], Awaitable[str]]


@dataclass
class ScoreRow:
    instance_id: str
    variant: str
    trial_idx: int
    info_recall: float | None
    analysis: float | None
    presentation: float | None
    total: float | None
    failure_stage: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_task_dataset(dataset_path: Path | str) -> dict[str, dict[str, Any]]:
    """读 DRB2 数据集, 构建 ``{case_id: {"prompt": str, "rubric": {dim: [items]}}}``.

    case_id 与 manifest 的 ``source_task_id`` 对齐 (``drb2_{idx}``)。
    只在这里 (打分侧) 读打分内容 —— runner 进程不碰此文件。
    """
    out: dict[str, dict[str, Any]] = {}
    with open(dataset_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            content = row.get("content") or {}
            rubric = content.get("rubric") or {}
            cid = f"drb2_{row.get('idx')}"
            out[cid] = {
                "prompt": row.get("prompt", ""),
                "description": row.get("description", ""),
                "rubric": {
                    d: list(rubric.get(d) or []) for d in _DIMENSIONS
                },
            }
    return out


# ---------------------------------------------------------------- judge client


_model_client: tuple[Any, dict[str, Any]] | None = None


def _build_judge_client() -> tuple[Any, dict[str, Any]]:
    """Lazy 构造 pi_ai models + 解析模型 dict (OPENAI_BASE_URL 覆盖, 同 A1)."""
    global _model_client
    if _model_client is not None:
        return _model_client
    from earendil_works.pi_ai import create_models
    from earendil_works.pi_ai.providers.openai import openai_provider

    models = create_models()
    models.setProvider(openai_provider())
    model_id = os.environ.get("OPENAI_MODEL", "")
    candidates = [m for m in models.getModels() if m.get("id") == model_id] if model_id else []
    if candidates:
        model = dict(candidates[0])
        if os.environ.get("OPENAI_BASE_URL"):
            model["baseUrl"] = os.environ["OPENAI_BASE_URL"]
    else:
        model = {
            "id": model_id or "gpt-4o",
            "name": model_id or "gpt-4o",
            "api": "openai-completions",
            "provider": "openai",
            "baseUrl": os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1",
            "reasoning": False,
            "input": ["text"],
            "maxTokens": 8192,
        }
    _model_client = (models, model)
    return _model_client


async def _message_text_of(stream: Any) -> str:
    """从 pi_ai streamSimple 事件流收集最终 assistant 文本. (同 A1 处理)"""
    text_parts: list[str] = []
    async for event in stream:
        if not isinstance(event, dict):
            continue
        et = event.get("type")
        if et == "text":
            t = event.get("text") or event.get("partial") or ""
            if isinstance(t, str):
                text_parts.append(t)
        elif et == "done":
            msg = event.get("message") or {}
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, str) and content:
                return content
            if isinstance(content, list):
                chunks: list[str] = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        chunks.append(str(block.get("text") or ""))
                return "".join(chunks)
            return "".join(text_parts)
        elif et == "error":
            return "".join(text_parts)
    return "".join(text_parts)


async def default_judge_fn(prompt: str) -> str:
    """默认 judge: pi_ai streamSimple, env 配置的模型 (同 A1)."""
    models, model = _build_judge_client()
    stream = models.streamSimple(
        model,
        {"messages": [{"role": "user", "content": prompt}], "maxTokens": _JUDGE_OUTPUT_TOKEN_CAP},
    )
    return await _message_text_of(stream)


# --------------------------------------------------------------- judge prompt


def _judge_prompt(task: dict[str, Any], item: str, report: str) -> str:
    return (
        "You are an expert research-report evaluator. Given a research task, one binary "
        "rubric item, and a model-generated report, judge whether the report satisfies "
        "the rubric.\n\n"
        f"TASK:\n{task['prompt']}\n\n"
        "Note: the task may list references that are BLOCKED (the report must NOT quote "
        "them). If the report's supporting evidence relies on a blocked reference, the "
        "rubric is NOT satisfied.\n\n"
        f"RUBRIC ITEM:\n{item}\n\n"
        f"MODEL REPORT:\n{report[:12000]}\n\n"
        "Output ONLY valid JSON with EXACTLY these keys:\n"
        '{"score": 1|0|-1, "reason": "<one short sentence>", "evidence": "<verbatim supporting sentence from the report, or empty string>"}\n'
        "score semantics: 1 = report satisfies the rubric with valid evidence; "
        "0 = not mentioned; -1 = mentioned but its evidence relies on a blocked reference."
    )


def _parse_judge_json(text: str) -> int | None:
    """解析 judge 响应, 提取 score (1/0/-1). 解析失败 -> None (按 0 处理)."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r'"score"\s*:\s*(-?1|0)', text)
        return int(m.group(1)) if m else None
    if isinstance(obj, dict):
        score = obj.get("score")
        if score in (1, 0, -1):
            return int(score)
    return None


async def _judge_item(
    task: dict[str, Any], item: str, report: str, judge_fn: JudgeFn
) -> int:
    """judge 单条 rubric -> score (默认 0 未提及). 超时/失败按未提及计, 不中断."""
    try:
        text = await asyncio.wait_for(
            judge_fn(_judge_prompt(task, item, report)), timeout=_JUDGE_CALL_TIMEOUT_S
        )
    except Exception:  # noqa: BLE001 — judge 失败按未提及计, 不中断整个 case
        return 0
    score = _parse_judge_json(text)
    return score if score is not None else 0


def _dimension_score(judgments: list[int]) -> float:
    """维度得分 = 通过 (score==1) 比例."""
    if not judgments:
        return 0.0
    return sum(1 for s in judgments if s == 1) / len(judgments)


def _total_score(dim_scores: list[float]) -> float | None:
    if not dim_scores:
        return None
    return sum(dim_scores) / len(dim_scores)


# ------------------------------------------------------------ orchestration


async def run_drb2_evaluation(
    *,
    response_root: Path | str,
    result_save_root: Path | str,
    dataset_path: Path | str,
    model_config_name: str,
    trial_num: int,
    judge_fn: JudgeFn | None = None,
    max_items: int | None = None,
) -> list[ScoreRow]:
    """对归一化报告逐个 case 打分（rubric judge）, 写结果 JSON, 返回 ScoreRow 列表.

    每个 case: 读报告 -> 对每条 rubric judge -> 维度得分 -> 总分。
    ``judge_fn`` 可注入 (离线单测); 默认用 pi_ai 走 env 配置模型。
    ``max_items`` 供 smoke 限速 (每维度最多 judge 条数; None = 全部)。
    """
    judge = judge_fn or default_judge_fn
    tasks = load_task_dataset(dataset_path)
    response_root = Path(response_root)
    result_root = Path(result_save_root)
    result_root.mkdir(parents=True, exist_ok=True)

    report_files = sorted(response_root.glob(f"{model_config_name}_*_*.md"))
    if not report_files:
        # F6-equivalent: 无报告 -> 空结果 (orchestrator 侧按 evaluator_failed 处理)
        return []

    def _parse_report_name(stem: str) -> tuple[str, int] | None:
        """从 ``<model_config_name>_<instance_id>_<trial>.md`` 拆 instance_id + trial.

        instance_id 可能含下划线 (drb2_22), model_config_name 也含 (competitorlens_a2),
        因此按前缀 + 尾部 trial 拆分 (不按固定段数).
        """
        prefix = f"{model_config_name}_"
        if not stem.startswith(prefix):
            return None
        rest = stem[len(prefix):]
        *id_parts, trial_str = rest.rsplit("_", 1)
        if not id_parts:
            return None
        try:
            return "_".join(id_parts), int(trial_str)
        except ValueError:
            return None

    rows: list[ScoreRow] = []
    for report_file in report_files:
        name = report_file.name
        stem = name[: -len(".md")]
        parsed = _parse_report_name(stem)
        if parsed is None:
            continue
        instance_id, trial = parsed
        if trial != trial_num:
            continue
        report = report_file.read_text(encoding="utf-8")
        task = tasks.get(instance_id)
        if task is None:
            rows.append(
                ScoreRow(instance_id=instance_id, variant=model_config_name,
                         trial_idx=trial, info_recall=None, analysis=None,
                         presentation=None, total=None,
                         failure_stage="missing_task")
            )
            continue
        dim_scores: dict[str, float] = {}
        failure: str | None = None
        try:
            for dim in _DIMENSIONS:
                items = task["rubric"].get(dim) or []
                if max_items is not None:
                    items = items[:max_items]
                judgments = [await _judge_item(task, it, report, judge) for it in items]
                dim_scores[dim] = _dimension_score(judgments)
        except Exception:  # noqa: BLE001
            failure = "judge_error"
            for dim in _DIMENSIONS:
                dim_scores.setdefault(dim, None)
        total = _total_score([dim_scores.get(d) for d in _DIMENSIONS if dim_scores.get(d) is not None])
        row = ScoreRow(
            instance_id=instance_id, variant=model_config_name, trial_idx=trial,
            info_recall=dim_scores.get("info_recall"),
            analysis=dim_scores.get("analysis"),
            presentation=dim_scores.get("presentation"),
            total=total, failure_stage=failure,
        )
        rows.append(row)
        (result_root / f"{name.replace('.md', '')}_eval_result.json").write_text(
            json.dumps(row.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return rows


def parse_scores(*, raw_dir: Path | str, model_config_name: str, trial_num: int) -> list[ScoreRow]:
    """从 ``{model_config_name}_*_{trial}_eval_result.json`` 读回 ScoreRow."""
    raw = Path(raw_dir)
    rows: list[ScoreRow] = []
    for f in sorted(raw.glob(f"{model_config_name}_*_eval_result.json")):
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        try:
            rows.append(
                ScoreRow(**{k: obj[k] for k in ScoreRow.__dataclass_fields__ if k in obj})
            )
        except (KeyError, TypeError):
            continue
    return [r for r in rows if r.trial_idx == trial_num]


__all__ = [
    "DIMENSIONS",
    "JudgeFn",
    "ScoreRow",
    "default_judge_fn",
    "load_task_dataset",
    "parse_scores",
    "run_drb2_evaluation",
]
