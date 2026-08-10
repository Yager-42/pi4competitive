"""WideSearch input adapter (D5 §5.2).

从 widesearch.jsonl 一行 -> CaseManifest. 只读 query + evaluation.required
(公开要求), 不读 gold CSV cell. competitors 从 query 文本启发式抽取明确点名
的实体 (S4 规则: 必须 >=1, 否则 raise).
"""
from __future__ import annotations

import json
import re
from typing import Any

from eval.manifest import CaseManifest, ManifestResearchBrief, TargetIdentity

# 启发式: query 里 "X vs Y" / "X compared to Y" / "X or Y" 抽实体对
_VS_PATTERN = re.compile(r"(.+?)\s+(?:vs\.?|versus|compared\s+to|or)\s+(.+)", re.IGNORECASE)


def parse_widesearch_row(row: dict[str, Any]) -> dict[str, Any]:
    """解析 widesearch.jsonl 一行, 提取 instance_id/query/required/language."""
    eval_str = row.get("evaluation", "{}")
    try:
        eval_obj = json.loads(eval_str) if isinstance(eval_str, str) else (eval_str or {})
    except json.JSONDecodeError:
        eval_obj = {}
    return {
        "instance_id": row["instance_id"],
        "query": row["query"],
        "required": eval_obj.get("required", []),
        "language": row.get("language", "en"),
    }


def _extract_competitors(query: str) -> list[str]:
    """从 query 抽明确点名的实体 (S4). 至少 1 个, 否则 raise."""
    m = _VS_PATTERN.search(query)
    if not m:
        raise ValueError(
            f"query has no明确 competitors (vs/compared to/or pattern); "
            f"cannot construct ResearchBrief.competitors (S4 rule): {query[:80]}"
        )
    # 简化: 取 vs 前后的实体 (粗粒度, manifest 评审时人工 confirm)
    left = m.group(1).strip().split(".")[-1].strip()  # 取最后一句话的实体
    right = m.group(2).strip().split(",")[0].split(".")[0].strip()
    comps = [c for c in (left, right) if c]
    if len(comps) < 1:
        raise ValueError(f"competitors extraction failed: {query[:80]}")
    return comps


def build_case_manifest(row: dict[str, Any], benchmark_revision: str) -> CaseManifest:
    """widesearch.jsonl row -> CaseManifest (不读 gold)."""
    parsed = parse_widesearch_row(row)
    competitors = _extract_competitors(parsed["query"])
    return CaseManifest(
        case_id=parsed["instance_id"],
        benchmark="widesearch",
        benchmark_revision=benchmark_revision,
        language=parsed["language"],
        category="business",
        source_task_id=parsed["instance_id"],
        query=parsed["query"],
        research_brief=ManifestResearchBrief(
            target=TargetIdentity(name=f"widesearch:{parsed['instance_id']}", category="benchmark"),
            goal=parsed["query"],
            competitors=competitors,
            dimensions=parsed["required"],
        ),
        license="MIT",
        notes="",
    )


__all__ = ["parse_widesearch_row", "build_case_manifest"]
