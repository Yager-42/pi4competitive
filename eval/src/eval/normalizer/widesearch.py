"""WideSearch normalizer (D10 N1).

report.md -> 确定性 Markdown table 提取 -> WideSearchResponse JSONL.
规则 (基准文档 §5.3): 找含 required headers 的表; 多候选取 header 覆盖最高;
找不到留空 response (F5 -> scorer 0 分); 禁 LLM 修复.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_TABLE_PATTERN = re.compile(
    r"(?:^|\n)((?:\|[^\n]+\|\s*\n)(?:\|[\s\-:|]+\|\s*\n)(?:\|[^\n]+\|\s*\n?)+)",
    re.MULTILINE,
)


def extract_markdown_table(report_md: str, required: list[str]) -> str | None:
    """找含全部 required headers 的第一个表; 找不到返回 None."""
    required_norm = {h.strip().lower() for h in required}
    matches = _TABLE_PATTERN.findall(report_md)
    best: str | None = None
    best_coverage = 0
    for m in matches:
        # header row = first line
        header_line = m.strip().split("\n")[0]
        headers = [h.strip().lower().strip("| ") for h in header_line.split("|") if h.strip()]
        coverage = sum(1 for r in required_norm if r in headers)
        if coverage == len(required_norm):
            return m.strip()
        if coverage > best_coverage:
            best_coverage = coverage
            best = m.strip()
    # 若没全匹配, 基准文档 §5.3.5: 找不到合法表保留原始输出 (这里返回 best 或 None)
    return best if best_coverage > 0 else None


def normalize_report(
    *,
    report_md: str,
    required_headers: list[str],
    instance_id: str,
    model_config_name: str,
    trial_idx: int,
    out_path: Path | str,
) -> None:
    """提表 -> WideSearchResponse JSONL. 无表 -> empty response (F5)."""
    table = extract_markdown_table(report_md, required_headers)
    response = table if table is not None else ""
    obj: dict[str, Any] = {
        "instance_id": instance_id,
        "response": response,
        "messages": [],
        "trial_idx": trial_idx,
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


__all__ = ["extract_markdown_table", "normalize_report"]
