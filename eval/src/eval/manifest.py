"""CaseManifest schema + loader (D5).

manifest 只从 query 推导 ResearchBrief, 不含 gold cell. benchmark 字段限定
widesearch/drb2 (双轨通用, D1). competitors >= 1 (domain ResearchBrief 约束).

ManifestResearchBrief 镜像 competitive_app.domain.research_brief.ResearchBrief
(target/goal/competitors/dimensions, min_length 约束对齐), 但为 eval 包自有类型,
不 import competitive_app.domain, 避免跨包耦合。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TargetIdentity(BaseModel):
    """镜像 competitive_app.domain.research_brief.TargetIdentity."""

    model_config = ConfigDict(extra="forbid")

    name: str = ""
    category: str = ""


class ManifestResearchBrief(BaseModel):
    """manifest 内嵌的 ResearchBrief (镜像 competitive_app.domain.research_brief)."""

    model_config = ConfigDict(extra="forbid")

    target: TargetIdentity
    goal: str = Field(min_length=1)
    competitors: list[str] = Field(min_length=1)
    dimensions: list[str] = Field(min_length=1)


class CaseManifest(BaseModel):
    """单 case manifest (基准文档 §5.1)."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    benchmark: Literal["widesearch", "drb2"]
    benchmark_revision: str = Field(min_length=1)
    language: Literal["en", "zh"]
    category: str = ""
    source_task_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    research_brief: ManifestResearchBrief
    license: str = ""
    notes: str = ""


def load_manifest(path: Path | str) -> list[CaseManifest]:
    """读 JSONL manifest, 每行一 case. 空行跳过."""
    p = Path(path)
    cases: list[CaseManifest] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        cases.append(CaseManifest.model_validate(json.loads(line)))
    return cases


__all__ = ["CaseManifest", "ManifestResearchBrief", "TargetIdentity", "load_manifest"]
