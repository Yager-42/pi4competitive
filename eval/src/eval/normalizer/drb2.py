"""DRB II report normalizer (D1 C2-wide).

基准文档 §10.2.5: 对 DRB II 报告只做编码/文件名规范化 —— 不做表格抽取、不做
LLM 修复。报告以 UTF-8 markdown 落盘到 ``normalized/drb2_reports/``，
文件名 ``competitorlens_{variant}_{instance_id}_{trial_idx}.md``，
供打分侧 evaluator 读取。

Gold 隔离：本模块位于 runner 进程路径 (normalizer)，源码不得出现 gold 标记
字符串（tests/eval/contract test_gold_isolation.py 扫描）。
"""
from __future__ import annotations

from pathlib import Path


def normalize_report(
    *,
    report_md: str,
    instance_id: str,
    model_config_name: str,
    trial_idx: int,
    out_path: Path | str,
) -> None:
    """把模型报告以 UTF-8 写盘（编码/文件名规范化）。

    空报告也写（打分侧按 0 分处理，与 WideSearch 空响应同语义）。
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report_md or "", encoding="utf-8")


def build_report_path(
    *,
    reports_root: Path | str,
    model_config_name: str,
    instance_id: str,
    trial_idx: int,
) -> Path:
    """构造归一化报告文件名（评分侧读取同一约定）。"""
    return (
        Path(reports_root)
        / f"{model_config_name}_{instance_id}_{trial_idx}.md"
    )


__all__ = ["build_report_path", "normalize_report"]
