"""DRB II input adapter (D1 C2-wide).

从 DeepResearch Bench II dataset 的一行 -> CaseManifest。只读 ``prompt`` /
``description`` / ``idx`` / ``language`` / ``theme`` / ``license`` —— 绝不读
打分侧内容（打分维度只挂载 evaluator，见 gold 隔离契约）。

Gold 隔离：本模块位于 runner 进程路径（adapter），源码不得出现打分侧数据
路径/字段标记字符串（tests/eval/contract 的 AST 扫描）。manifest 由人工整理
（``eval/manifests/drb2_smoke.jsonl``），本 adapter 仅作候选生成 / manifest
构建的 dev 助手，不参与运行期数据流。

DRB II 任务是长文研究报告题（无 WideSearch 的 "vs" 模式），competitors 用
启发式从 prompt 抽实体，抽不到时退回 ``description``（manifest 评审时人工
修正，基准文档 §3.2 versioned manifest）。
"""
from __future__ import annotations

import re
from typing import Any

from eval.manifest import CaseManifest, ManifestResearchBrief, TargetIdentity

# 从 prompt 抽实体: 连续大写词 (长度 >= 2) 短语
_ENTITY_PATTERN = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b")
# 常见的句首/非实体词
_STOP = {
    "I",
    "A",
    "The",
    "This",
    "That",
    "Please",
    "Hello",
    "Specifically",
    "My",
    "Our",
    "We",
    "Could",
    "Would",
    "How",
    "What",
    "Part",
    "One",
    "First",
    "Second",
    "Third",
    "Entire",
    "Different",
    "Electric",
    "Vehicle",
    "Life",
    "Cost",
    "Horizontal",
    "Gene",
    "Transfer",
    "Between",
    "Parasitic",
    "Plants",
    "Types",
    "Comparison",
    "Research",
    "Status",
    "Detailed",
    "Report",
    "May",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
}


def parse_drb2_row(row: dict[str, Any]) -> dict[str, Any]:
    """解析 dataset 一行, 提取 manifest 需要的公开字段 (不含打分侧)."""
    return {
        "idx": row.get("idx"),
        "id": row.get("id", ""),
        "language": row.get("language", "en"),
        "theme": row.get("theme", ""),
        "description": row.get("description", ""),
        "prompt": row.get("prompt", ""),
        "license": row.get("license", ""),
    }


def _extract_entities(prompt: str, limit: int = 6) -> list[str]:
    """从 prompt 抽实体 (去 stop 词, 去重, 保序). 无命中 -> 空列表."""
    out: list[str] = []
    for m in _ENTITY_PATTERN.findall(prompt[:600]):
        head = m.split()[0]
        if head in _STOP or len(m) < 4:
            continue
        if m not in out:
            out.append(m)
        if len(out) >= limit:
            break
    return out


def build_case_manifest(row: dict[str, Any], benchmark_revision: str) -> CaseManifest:
    """dataset row -> CaseManifest (只读 prompt/description/license)."""
    parsed = parse_drb2_row(row)
    cid = f"drb2_{parsed['idx']}"
    entities = _extract_entities(parsed["prompt"])
    competitors = entities or [parsed["description"][:60] or cid]
    return CaseManifest(
        case_id=cid,
        benchmark="drb2",
        benchmark_revision=benchmark_revision,
        language=parsed["language"],
        category=parsed["theme"] or "business",
        source_task_id=cid,
        query=parsed["prompt"],
        research_brief=ManifestResearchBrief(
            target=TargetIdentity(name=parsed["description"] or cid, category="benchmark"),
            goal=parsed["prompt"],
            competitors=competitors,
            # DRB II 是长文报告题, 无 WideSearch 那样的必需列 -> 用通用维度
            # (plan 阶段据此生成最小 coverage schema; 报告质量由打分侧 rubric 衡量)
            dimensions=["overview"],
        ),
        license=parsed["license"] or "CC BY 4.0",
        notes=f"DRB2 dataset id={parsed['id']} idx={parsed['idx']} theme={parsed['theme']}",
    )


__all__ = ["build_case_manifest", "parse_drb2_row"]
