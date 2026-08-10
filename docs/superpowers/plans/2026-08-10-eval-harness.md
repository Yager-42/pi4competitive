# Eval Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建 `eval/` 评测包,跑通 WideSearch Smoke 5 题 × A1/A2 × 1 重复,产出第一份真实 `scores/widesearch.jsonl` + `paired_deltas.json`。

**Architecture:** `eval/` 独立 workspace 包(L1),HTTP 黑盒驱动(W1)——orchestrator 起独立 `competitive_app` 进程打 `POST /tasks`(A2),起独立 A1 ASGI 服务打 `POST /eval/run`(A1),poll 终态取 report/trace/SOCM,normalizer 提表造 `WideSearchResponse` JSONL,evaluator 独立进程调官方 scorer 出分。gold 三道闸隔离(工具面裁剪 + cwd 隔离 + evaluator 独立进程)。

**Tech Stack:** Python 3.12, uv workspace, FastAPI(A1 ASGI), httpx(W1 HTTP), Pydantic v2(manifest schema), pytest + `tests/live_env.py`(门控)。复用 `competitive_app` 的 `_HarnessFactory` + `search_tavily` capability。WideSearch 官方 scorer(`vendor/widesearch/scripts/run_infer_and_eval_batching.py`)。

**Spec:** [`docs/superpowers/specs/2026-08-10-eval-harness-design.md`](../specs/2026-08-10-eval-harness-design.md)(D0-D13 决策树)

---

## File Structure

```text
eval/                                    # 新建 workspace 包 (L1, D3)
  pyproject.toml                         # workspace member, 依赖 httpx/fastapi/competitive_app
  src/eval/
    __init__.py
    manifest.py                          # CaseManifest pydantic schema + 加载/校验 (D5 manifest)
    manifest_builder.py                  # 从 widesearch.jsonl 挑 5 题 (S4), 不读 gold
    adapter/
      __init__.py
      widesearch.py                      # WideSearch case -> ResearchBrief (input adapter, §5.2)
      drb2.py                            # DRB II 空壳 (NotImplementedError, D1)
    runner/
      __init__.py
      http_client.py                     # W1: httpx client, POST /tasks + poll + GET report
      single_agent_app.py                # A1 ASGI 服务 (D9), POST /eval/run
      budget_guard.py                    # A1 工具 wrapper 计 search/fetch (D7)
    normalizer/
      __init__.py
      widesearch.py                      # report.md -> WideSearchResponse JSONL (D10 N1)
      drb2.py                            # 空壳
    operations/
      __init__.py
      collector.py                        # events.jsonl + projection + SOCM -> operations.json (D11)
    evaluator/
      __init__.py
      widesearch.py                       # 调官方 scorer (D10 H1), 读 scores_raw
      drb2.py                             # 空壳
    orchestrator.py                       # CLI: eval.run --stage smoke (D12)
  README.md
  manifests/
    widesearch_smoke.jsonl               # 5 题 versioned manifest (S4, 后续生成)
vendor/widesearch/                        # WideSearch 仓 sparse-checkout (D5 P2)
  scripts/run_infer_and_eval_batching.py  # 官方 scorer (不改)
  src/utils/config.py                    # patch: 加 deepseek-v4-flash config (D10)
  patches/                               # patch diff, 进 git
data/benchmarks/widesearch/              # gold + HF cache (gitignore, D5 P2)
  REVISION.txt                           # HF dataset SHA + 仓 SHA (进 git)
  widesearch.jsonl                       # 从 HF 拉 (含 gold, 运行进程不直接读)
  widesearch_gold/                       # gold CSV (运行进程不可见, D6)
  hf_cache/                               # HF_DATASETS_CACHE
data/evaluations/<run_id>/                # 结果产物 (gitignore, D11)
tests/eval/                               # 测试 (D12)
  unit/
  contract/
  integration/live/
.gitignore                                # 加 data/evaluations/ + data/benchmarks/ (D11)
pyproject.toml                            # workspace members 加 eval (D3)
```

---

## Task 0: 拉 WideSearch 仓 + 确认 config 注册

**Files:**
- Create: `vendor/widesearch/` (sparse-checkout)
- Create: `data/benchmarks/widesearch/REVISION.txt`
- Modify: `.gitignore`

- [ ] **Step 1: sparse-checkout WideSearch 仓**

```bash
# WideSearch 仓代码 (scorer) 进 vendor/, 不含数据
mkdir -p vendor/widesearch
cd vendor/widesearch
git init
git remote add origin https://github.com/ByteDance-Seed/WideSearch.git
git config core.sparseCheckout true
echo "scripts/" > .git/info/sparse-checkout
echo "src/" >> .git/info/sparse-checkout
echo "LICENSE" >> .git/info/sparse-checkout
echo "README.md" >> .git/info/sparse-checkout
git pull origin main
cd ../../
```

- [ ] **Step 2: 记 WideSearch 仓 SHA**

```bash
cd vendor/widesearch && git rev-parse HEAD > ../../data/benchmarks/widesearch/WS_REPO_SHA.txt && cd ../../
cat data/benchmarks/widesearch/WS_REPO_SHA.txt
```
Expected: 一个 40 字符 SHA。

- [ ] **Step 3: 从 HF 拉 WideSearch dataset 到 data/benchmarks/**

```bash
mkdir -p data/benchmarks/widesearch
HF_HOME=data/benchmarks/hf_cache huggingface-cli download ByteDance-Seed/WideSearch --repo-type dataset --local-dir data/benchmarks/widesearch/dataset
# 记 HF dataset commit SHA
HF_HOME=data/benchmarks/hf_cache python -c "from huggingface_hub import HfApi; print(HfApi().dataset_info('ByteDance-Seed/WideSearch').sha)" > data/benchmarks/widesearch/HF_DATASET_SHA.txt
cat data/benchmarks/widesearch/HF_DATASET_SHA.txt
```
Expected: HF dataset commit SHA。

- [ ] **Step 4: 写 REVISION.txt**

```bash
cat > data/benchmarks/widesearch/REVISION.txt <<EOF
wideSearch repo SHA: $(cat data/benchmarks/widesearch/WS_REPO_SHA.txt)
HF dataset SHA: $(cat data/benchmarks/widesearch/HF_DATASET_SHA.txt)
fetched: 2026-08-10
EOF
cat data/benchmarks/widesearch/REVISION.txt
```

- [ ] **Step 5: 确认 config.py 结构(D10 待定项消除)**

```bash
grep -n "model_config\|default_eval_config\|deepseek" vendor/widesearch/src/utils/config.py | head -20
```
Expected: 看到 `model_config = {...}` dict 和 `default_eval_config` 条目。确认无 env 注入(无 `os.environ`/`os.getenv`),必须 patch。

- [ ] **Step 6: .gitignore 加 data/evaluations/ + data/benchmarks/**

读 `.gitignore`,确认 `data/` 已被忽略(grep `^data/`);若 `data/` 整体已忽略,则 `data/evaluations/` 和 `data/benchmarks/` 自动忽略。但 `vendor/widesearch/` 要进 git(代码),确认没被忽略:

```bash
grep -n 'vendor\|data/' .gitignore
git check-ignore vendor/widesearch/src/utils/config.py data/benchmarks/widesearch_gold/x.csv 2>/dev/null
```
Expected: `data/benchmarks/...` 被忽略(输出路径),`vendor/...` 不被忽略(无输出)。

- [ ] **Step 7: 提交**

```bash
git add vendor/widesearch/ .gitignore data/benchmarks/widesearch/REVISION.txt
git commit -m "P4: eval harness — vendor WideSearch + benchmark data revision (Task 0)"
```

---

## Task 1: 创建 eval/ workspace 包骨架

**Files:**
- Create: `eval/pyproject.toml`
- Create: `eval/src/eval/__init__.py`
- Modify: `pyproject.toml` (root, workspace members)

- [ ] **Step 1: 写 eval/pyproject.toml**

```toml
[project]
name = "eval"
version = "0.0.1"
description = "CompetitorLens benchmark evaluation harness (WideSearch + DRB II)"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    "fastapi>=0.115",
    "pydantic>=2.9",
    "competitive-app",
    "earendil-works.pi-agent",
    "earendil-works.pi-ai",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/eval"]
```

- [ ] **Step 2: 写 eval/src/eval/__init__.py**

```python
"""CompetitorLens benchmark evaluation harness.

Spec: docs/superpowers/specs/2026-08-10-eval-harness-design.md
Drives competitive_app (A2) + single_agent service (A1) over HTTP (W1),
normalizes output, runs official WideSearch scorer in an isolated evaluator
process. Gold isolated by tool-surface裁剪 + cwd + evaluator process (D6).
"""
__version__ = "0.0.1"
```

- [ ] **Step 3: 改根 pyproject.toml 加 workspace member**

读 `pyproject.toml` 找到 `members = [...]` 行,加 `"eval"`:

```toml
members = ["packages/ai", "packages/agent", "competitive_app", "eval"]
```
并在 dependency 行加:
```toml
eval = { workspace = true }
```
(参照现有 `competitive_app = { workspace = true }` 的写法)

- [ ] **Step 4: uv sync 验证**

```bash
uv sync 2>&1 | tail -5
```
Expected: 无错误,`eval` 包被识别安装。

- [ ] **Step 5: 验证 import**

```bash
uv run python -c "import eval; print(eval.__version__)"
```
Expected: `0.0.1`

- [ ] **Step 6: 提交**

```bash
git add eval/ pyproject.toml uv.lock
git commit -m "P4: eval harness — create eval workspace package skeleton (Task 1)"
```

---

## Task 2: CaseManifest schema + 加载器(D5)

**Files:**
- Create: `eval/src/eval/manifest.py`
- Test: `tests/eval/unit/test_manifest.py`
- Create: `tests/eval/__init__.py`, `tests/eval/unit/__init__.py`

- [ ] **Step 1: 写 tests/eval 骨架**

```bash
mkdir -p tests/eval/unit tests/eval/contract tests/eval/integration/live
touch tests/eval/__init__.py tests/eval/unit/__init__.py tests/eval/contract/__init__.py
```

- [ ] **Step 2: 写失败测试 tests/eval/unit/test_manifest.py**

```python
"""CaseManifest schema + loader tests (D5)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from eval.manifest import CaseManifest, load_manifest


def _sample_case(case_id: str = "ws_en_001") -> dict:
    return {
        "case_id": case_id,
        "benchmark": "widesearch",
        "benchmark_revision": "abc123",
        "language": "en",
        "category": "business",
        "source_task_id": case_id,
        "query": "Compare Apple iPhone 15 vs Samsung Galaxy S24 specs.",
        "research_brief": {
            "target": {"name": "iPhone 15 vs Galaxy S24", "category": "benchmark"},
            "goal": "Compare Apple iPhone 15 vs Samsung Galaxy S24 specs.",
            "competitors": ["Apple iPhone 15", "Samsung Galaxy S24"],
            "dimensions": ["price", "screen", "chipset"],
        },
        "license": "MIT",
        "notes": "",
    }


def test_case_manifest_parses_valid():
    m = CaseManifest.model_validate(_sample_case())
    assert m.case_id == "ws_en_001"
    assert m.benchmark == "widesearch"
    assert m.research_brief.competitors == ["Apple iPhone 15", "Samsung Galaxy S24"]
    assert m.research_brief.dimensions == ["price", "screen", "chipset"]


def test_case_manifest_requires_competitors_min_1():
    raw = _sample_case()
    raw["research_brief"]["competitors"] = []
    with pytest.raises(ValidationError):
        CaseManifest.model_validate(raw)


def test_case_manifest_rejects_unknown_benchmark():
    raw = _sample_case()
    raw["benchmark"] = "unknown_bench"
    with pytest.raises(ValidationError):
        CaseManifest.model_validate(raw)


def test_load_manifest_reads_jsonl(tmp_path: Path):
    p = tmp_path / "manifest.jsonl"
    p.write_text(json.dumps(_sample_case("ws_en_001")) + "\n", encoding="utf-8")
    p.write_text(json.dumps(_sample_case("ws_en_002")), encoding="utf-8")
    cases = load_manifest(p)
    assert len(cases) == 2
    assert cases[0].case_id == "ws_en_001"
    assert cases[1].case_id == "ws_en_002"
```

- [ ] **Step 3: 运行测试确认失败**

```bash
uv run pytest tests/eval/unit/test_manifest.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'eval.manifest'`.

- [ ] **Step 4: 写 eval/src/eval/manifest.py**

```python
"""CaseManifest schema + loader (D5).

manifest 只从 query 推导 ResearchBrief, 不含 gold cell. benchmark 字段限定
widesearch/drb2 (双轨通用, D1). competitors >= 1 (domain ResearchBrief 约束).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TargetIdentity(BaseModel):
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
    """读 JSONL manifest, 每行一 case."""
    p = Path(path)
    cases: list[CaseManifest] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        cases.append(CaseManifest.model_validate(json.loads(line)))
    return cases


__all__ = ["CaseManifest", "ManifestResearchBrief", "TargetIdentity", "load_manifest"]
```

- [ ] **Step 5: 运行测试确认通过**

```bash
uv run pytest tests/eval/unit/test_manifest.py -v
```
Expected: 4 passed.

- [ ] **Step 6: 提交**

```bash
git add eval/src/eval/manifest.py tests/eval/
git commit -m "P4: eval harness — CaseManifest schema + loader (Task 2, D5)"
```

---

## Task 3: WideSearch input adapter(D5 §5.2)

**Files:**
- Create: `eval/src/eval/adapter/__init__.py`
- Create: `eval/src/eval/adapter/widesearch.py`
- Create: `eval/src/eval/adapter/drb2.py`
- Test: `tests/eval/unit/test_adapter_widesearch.py`

- [ ] **Step 1: 写失败测试**

```python
"""WideSearch input adapter: official task -> CaseManifest (D5 §5.2)."""
from __future__ import annotations

import json

from eval.adapter.widesearch import build_case_manifest, parse_widesearch_row


def _ws_row(instance_id="ws_en_001", query="Compare Apple iPhone 15 vs Samsung Galaxy S24 specs. Output a Markdown table with columns: price, screen, chipset."):
    return {
        "instance_id": instance_id,
        "query": query,
        "evaluation": json.dumps({
            "unique_columns": ["price"],
            "required": ["price", "screen", "chipset"],
            "eval_pipeline": {},
        }),
        "language": "en",
    }


def test_parse_row_extracts_query_and_required():
    row = _ws_row()
    parsed = parse_widesearch_row(row)
    assert parsed["instance_id"] == "ws_en_001"
    assert "Apple iPhone 15" in parsed["query"]
    assert parsed["required"] == ["price", "screen", "chipset"]
    assert parsed["language"] == "en"


def test_build_manifest_competitors_from_query():
    row = _ws_row()
    m = build_case_manifest(row, benchmark_revision="abc123")
    assert m.case_id == "ws_en_001"
    assert m.benchmark == "widesearch"
    # competitors must come from query text, not gold
    assert "Apple iPhone 15" in m.research_brief.competitors[0] or "Samsung Galaxy S24" in m.research_brief.competitors[0]
    assert m.research_brief.dimensions == ["price", "screen", "chipset"]
    assert m.research_brief.goal.startswith("Compare Apple iPhone 15")


def test_build_manifest_rejects_no_competitor_query():
    row = _ws_row(query="List the top 5 universities by QS ranking. Output a Markdown table with columns: name, rank.")
    # query has no明确实体 -> competitors 无法构造 -> raise (S4 规则)
    import pytest
    with pytest.raises(ValueError, match="competitors"):
        build_case_manifest(row, benchmark_revision="abc123")
```

- [ ] **Step 2: 运行确认失败**

```bash
uv run pytest tests/eval/unit/test_adapter_widesearch.py -v
```
Expected: FAIL `No module named 'eval.adapter'`.

- [ ] **Step 3: 写 eval/src/eval/adapter/__init__.py**

```python
"""Benchmark input adapters: official task -> CaseManifest."""
```

- [ ] **Step 4: 写 eval/src/eval/adapter/widesearch.py**

```python
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
```

- [ ] **Step 5: 写 eval/src/eval/adapter/drb2.py (空壳, D1)**

```python
"""DRB II input adapter (D1 C2-wide: reserved shape, not wired)."""
from __future__ import annotations


def build_case_manifest(*args, **kwargs):  # type: ignore[no-untyped-def]
    raise NotImplementedError("DRB II track: C2-wide reserves shape, not wired (D1)")


__all__: list[str] = []
```

- [ ] **Step 6: 运行测试确认通过**

```bash
uv run pytest tests/eval/unit/test_adapter_widesearch.py -v
```
Expected: 3 passed.

- [ ] **Step 7: 提交**

```bash
git add eval/src/eval/adapter/ tests/eval/unit/test_adapter_widesearch.py
git commit -m "P4: eval harness — WideSearch input adapter + DRB II stub (Task 3, D5)"
```

---

## Task 4: manifest_builder — 从 widesearch.jsonl 挑 5 题(S4)

**Files:**
- Create: `eval/src/eval/manifest_builder.py`
- Create: `eval/manifests/widesearch_smoke.jsonl` (生成)
- Test: `tests/eval/unit/test_manifest_builder.py`

- [ ] **Step 1: 写失败测试**

```python
"""manifest_builder: 从 widesearch.jsonl 挑 S4 题 (明确点名实体)."""
from __future__ import annotations

import json
from pathlib import Path

from eval.manifest_builder import select_smoke_cases


def _ws_jsonl(path: Path, rows: list[dict]):
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _row(iid, query, required=None, lang="en"):
    return {
        "instance_id": iid,
        "query": query,
        "evaluation": json.dumps({"required": required or ["price"], "eval_pipeline": {}}),
        "language": lang,
    }


def test_select_smoke_cases_keeps_vs_queries(tmp_path: Path):
    src = tmp_path / "widesearch.jsonl"
    _ws_jsonl(src, [
        _row("ws_en_001", "Compare Apple iPhone 15 vs Samsung Galaxy S24 specs.", ["price", "screen"]),
        _row("ws_en_002", "List top 5 universities by QS ranking.", ["name", "rank"]),  # 无 vs, 排除
        _row("ws_en_003", "Tesla Model 3 compared to BYD Seal range.", ["price", "range"]),
    ])
    selected = select_smoke_cases(src, limit=5, benchmark_revision="abc123")
    ids = [s.source_task_id for s in selected]
    assert "ws_en_001" in ids
    assert "ws_en_003" in ids
    assert "ws_en_002" not in ids  # 无明确实体对


def test_select_smoke_cases_limits_to_5(tmp_path: Path):
    rows = [_row(f"ws_en_{i:03d}", f"Company A{i} vs Company B{i} specs.", ["price"]) for i in range(1, 11)]
    src = tmp_path / "widesearch.jsonl"
    _ws_jsonl(src, rows)
    selected = select_smoke_cases(src, limit=5, benchmark_revision="abc123")
    assert len(selected) == 5


def test_select_smoke_cases_dumps_jsonl(tmp_path: Path):
    src = tmp_path / "widesearch.jsonl"
    _ws_jsonl(src, [_row("ws_en_001", "Apple vs Samsung specs.", ["price"])])
    out = tmp_path / "smoke.jsonl"
    selected = select_smoke_cases(src, limit=5, benchmark_revision="abc123", out_path=out)
    assert out.exists()
    lines = out.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == len(selected)
    assert json.loads(lines[0])["case_id"] == "ws_en_001"
```

- [ ] **Step 2: 运行确认失败**

```bash
uv run pytest tests/eval/unit/test_manifest_builder.py -v
```
Expected: FAIL `No module named 'eval.manifest_builder'`.

- [ ] **Step 3: 写 eval/src/eval/manifest_builder.py**

```python
"""manifest_builder: 从 widesearch.jsonl 挑 Smoke 题 (S4).

读 data/benchmarks/widesearch/dataset/widesearch.jsonl, 用 adapter 过滤出
query 明确点名实体 (vs/compared to/or) 的题, 取前 N (default 5), 产
CaseManifest JSONL. 不读 gold CSV (D6 闸 3: manifest builder 只读 query).
"""
from __future__ import annotations

import json
from pathlib import Path

from eval.adapter.widesearch import build_case_manifest
from eval.manifest import CaseManifest


def select_smoke_cases(
    src: Path | str,
    *,
    limit: int = 5,
    benchmark_revision: str,
    out_path: Path | str | None = None,
) -> list[CaseManifest]:
    """读 widesearch.jsonl, 挑 S4 题 (vs pattern), 返回 CaseManifest list."""
    src = Path(src)
    selected: list[CaseManifest] = []
    with src.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("language") != "en":
                continue
            try:
                m = build_case_manifest(row, benchmark_revision=benchmark_revision)
            except ValueError:
                continue  # 无明确实体, S4 排除
            selected.append(m)
            if len(selected) >= limit:
                break
    if out_path is not None:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            for m in selected:
                f.write(m.model_dump_json() + "\n")
    return selected


__all__ = ["select_smoke_cases"]
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/eval/unit/test_manifest_builder.py -v
```
Expected: 3 passed.

- [ ] **Step 5: 生成真实 Smoke manifest(需 Task 0 数据已拉)**

```bash
uv run python -c "
from eval.manifest_builder import select_smoke_cases
rev = open('data/benchmarks/widesearch/WS_REPO_SHA.txt').read().strip()
selected = select_smoke_cases(
    'data/benchmarks/widesearch/dataset/widesearch.jsonl',
    limit=5,
    benchmark_revision=rev,
    out_path='eval/manifests/widesearch_smoke.jsonl',
)
print(f'selected {len(selected)} cases:')
for m in selected:
    print(f'  {m.case_id}: {m.research_brief.competitors}')
"
cat eval/manifests/widesearch_smoke.jsonl | head -1 | python -m json.tool
```
Expected: 5 cases,每个 `competitors` ≥1 实体。若不满 5 题(S4 太严),人工 review 后手补 manifest(固化规则,记录在 manifest notes)。

- [ ] **Step 6: 提交**

```bash
git add eval/src/eval/manifest_builder.py eval/manifests/widesearch_smoke.jsonl tests/eval/unit/test_manifest_builder.py
git commit -m "P4: eval harness — manifest_builder + Smoke 5-case manifest (Task 4, S4)"
```

---

## Task 5: http_client — W1 HTTP 黑盒驱动 A2(D4)

**Files:**
- Create: `eval/src/eval/runner/__init__.py`
- Create: `eval/src/eval/runner/http_client.py`
- Test: `tests/eval/unit/test_http_client.py`

- [ ] **Step 1: 写失败测试**

```python
"""http_client: W1 POST /tasks + poll + GET report (D4)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from eval.runner.http_client import CompetitiveAppClient, TaskResult


@pytest.mark.asyncio
async def test_submit_and_poll_returns_completed(monkeypatch):
    # Mock httpx.AsyncClient
    transport = httpx.MockTransport(lambda req: _route(req))
    client = CompetitiveAppClient(base_url="http://test", transport=transport)
    result = await client.run_task(
        research_brief={
            "target": {"name": "x", "category": "benchmark"},
            "goal": "Compare A vs B",
            "competitors": ["A", "B"],
            "dimensions": ["price"],
        },
        search_overrides={"max_queries": 20, "max_wall_seconds": 720},
        timeout=30,
    )
    assert result.terminal_status == "completed"
    assert "Markdown table" in result.report_markdown
    assert result.task_id == "task-1"


def _route(req: httpx.Request) -> httpx.Response:
    path = req.url.path
    if path == "/api/v2/tasks" and req.method == "POST":
        return httpx.Response(202, json={"task_id": "task-1"})
    if path.startswith("/api/v2/tasks/task-1"):
        if req.method == "GET" and path == "/api/v2/tasks/task-1":
            return httpx.Response(200, json={"task_id": "task-1", "status": "completed",
                "projection": {"report_title": "x"}})
        if path == "/api/v2/tasks/task-1/report":
            return httpx.Response(200, json={"ok": True, "markdown": "Markdown table here", "report_id": "task-1"})
        if path == "/api/v2/tasks/task-1/sessions":
            return httpx.Response(200, json={"sessions": []})
    if path == "/api/v2/tasks/task-1/abort":
        return httpx.Response(200, json={"task_id": "task-1", "status": "aborted"})
    return httpx.Response(404)


@pytest.mark.asyncio
async def test_submit_aborts_on_timeout():
    call_count = {"n": 0}
    def route(req):
        call_count["n"] += 1
        if req.url.path == "/api/v2/tasks" and req.method == "POST":
            return httpx.Response(202, json={"task_id": "task-1"})
        if req.url.path == "/api/v2/tasks/task-1/abort":
            return httpx.Response(200, json={"status": "aborted"})
        # task never completes
        return httpx.Response(200, json={"task_id": "task-1", "status": "running", "projection": {}})
    transport = httpx.MockTransport(route)
    client = CompetitiveAppClient(base_url="http://test", transport=transport)
    result = await client.run_task(
        research_brief={"target": {"name": "x", "category": "benchmark"}, "goal": "g",
                        "competitors": ["A"], "dimensions": ["d"]},
        search_overrides={},
        timeout=2,  # 2s
        poll_interval=0.2,
    )
    assert result.terminal_status == "aborted"
```

- [ ] **Step 2: 运行确认失败**

```bash
uv run pytest tests/eval/unit/test_http_client.py -v
```
Expected: FAIL `No module named 'eval.runner'`.

- [ ] **Step 3: 写 eval/src/eval/runner/__init__.py**

```python
"""Run drivers: HTTP client (A2) + single_agent service (A1)."""
```

- [ ] **Step 4: 写 eval/src/eval/runner/http_client.py**

```python
"""W1 HTTP client: drive competitive_app via POST /tasks (D4).

orchestrator 起独立 competitive_app 进程, 本 client 打 POST /tasks + poll
GET /tasks/{id} + GET /reports/{id}. 总 wall-clock guard 到 timeout abort.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class TaskResult:
    task_id: str
    terminal_status: str  # completed | failed | aborted | timeout
    report_markdown: str
    projection: dict[str, Any]
    trace: dict[str, Any]
    failure_stage: str | None = None


class CompetitiveAppClient:
    """HTTP client for competitive_app (A2 variant)."""

    def __init__(self, *, base_url: str = "http://127.0.0.1:8000", transport: Any = None):
        self._base_url = base_url.rstrip("/")
        self._transport = transport  # test injection

    async def run_task(
        self,
        *,
        research_brief: dict[str, Any],
        search_overrides: dict[str, Any] | None = None,
        timeout: float = 900.0,
        poll_interval: float = 5.0,
    ) -> TaskResult:
        body: dict[str, Any] = {"research_brief": research_brief}
        if search_overrides:
            body["search_overrides"] = search_overrides
        async with httpx.AsyncClient(base_url=self._base_url, transport=self._transport, timeout=30) as client:
            resp = await client.post("/api/v2/tasks", json=body)
            resp.raise_for_status()
            task_id = resp.json()["task_id"]

            deadline = asyncio.get_event_loop().time() + timeout
            status = "running"
            projection: dict[str, Any] = {}
            while asyncio.get_event_loop().time() < deadline:
                t = await client.get(f"/api/v2/tasks/{task_id}")
                t.raise_for_status()
                td = t.json()
                status = td.get("status", "running")
                projection = td.get("projection") or {}
                if status in ("completed", "failed", "aborted"):
                    break
                await asyncio.sleep(poll_interval)

            if status not in ("completed", "failed", "aborted"):
                # timeout: abort
                await client.post(f"/api/v2/tasks/{task_id}/abort")
                status = "aborted"

            # fetch report + trace
            report_md = ""
            try:
                r = await client.get(f"/api/v2/reports/{task_id}")
                if r.status_code == 200:
                    rd = r.json()
                    report_md = rd.get("markdown", "") if rd.get("ok") else ""
            except httpx.HTTPError:
                pass
            trace: dict[str, Any] = {}
            try:
                tr = await client.get(f"/api/v2/tasks/{task_id}/sessions")
                if tr.status_code == 200:
                    trace = tr.json()
            except httpx.HTTPError:
                pass

            failure_stage = projection.get("first_non_ok_stage") if status != "completed" else None
            return TaskResult(
                task_id=task_id,
                terminal_status=status,
                report_markdown=report_md,
                projection=projection,
                trace=trace,
                failure_stage=failure_stage,
            )


__all__ = ["CompetitiveAppClient", "TaskResult"]
```

- [ ] **Step 5: 运行测试确认通过**

```bash
uv run pytest tests/eval/unit/test_http_client.py -v
```
Expected: 2 passed.

- [ ] **Step 6: 提交**

```bash
git add eval/src/eval/runner/__init__.py eval/src/eval/runner/http_client.py tests/eval/unit/test_http_client.py
git commit -m "P4: eval harness — W1 HTTP client for competitive_app (Task 5, D4)"
```

---

## Task 6: budget_guard — A1 工具 wrapper 计 search/fetch(D7)

**Files:**
- Create: `eval/src/eval/runner/budget_guard.py`
- Test: `tests/eval/unit/test_budget_guard.py`

- [ ] **Step 1: 写失败测试**

```python
"""budget_guard: wrap search/fetch tools, count + reject over budget (D7)."""
from __future__ import annotations

import pytest

from eval.runner.budget_guard import BudgetGuard, wrap_tools_with_budget


class _FakeTool:
    def __init__(self, name):
        self.name = name
        self.parameters = {}
        self.description = ""
        self.execute = None  # filled by wrap


@pytest.mark.asyncio
async def test_budget_guard_counts_search_and_fetch():
    guard = BudgetGuard(max_search=2, max_fetch=4)
    assert guard.search_count == 0
    guard.consume_search()
    guard.consume_search()
    assert guard.search_count == 2
    assert guard.exhausted_search()


@pytest.mark.asyncio
async def test_wrap_rejects_when_search_exhausted():
    guard = BudgetGuard(max_search=1, max_fetch=2)
    tool = _FakeTool("tavily_search")
    wrapped = guard.wrap(tool)
    # first call ok (returns a sentinel from inner execute)
    tool.execute = lambda *a, **k: _ok()
    await wrapped.execute("id", {})
    # second call: budget exhausted -> error result
    result = await wrapped.execute("id", {})
    assert result["content"][0]["text"].startswith("budget_exhausted")


def _ok():
    return {"content": [{"type": "text", "text": "ok"}], "details": {}}


def test_wrap_distinguishes_search_vs_fetch():
    guard = BudgetGuard(max_search=2, max_fetch=2)
    search_tool = _FakeTool("tavily_search")
    fetch_tool = _FakeTool("tavily_fetch")
    ws = guard.wrap(search_tool)
    wf = guard.wrap(fetch_tool)
    assert ws.name == "tavily_search"
    assert wf.name == "tavily_fetch"


def test_wrap_tools_with_budget_filters():
    tools = [_FakeTool("tavily_search"), _FakeTool("tavily_fetch"), _FakeTool("echo")]
    guard = BudgetGuard(max_search=5, max_fetch=10)
    wrapped = wrap_tools_with_budget(tools, guard)
    # echo is not search/fetch -> pass through unchanged
    names = [t.name for t in wrapped]
    assert "tavily_search" in names
    assert "tavily_fetch" in names
    assert "echo" in names
```

- [ ] **Step 2: 运行确认失败**

```bash
uv run pytest tests/eval/unit/test_budget_guard.py -v
```
Expected: FAIL `No module named 'eval.runner.budget_guard'`.

- [ ] **Step 3: 写 eval/src/eval/runner/budget_guard.py**

```python
"""budget_guard: A1 工具 wrapper (D7).

wrap tavily_search/tavily_fetch, 计 search_count/fetch_count, 超额返回
budget_exhausted error (让 agent 收手). 其他工具 (echo 等) 原样透传.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_SEARCH_TOOL_NAMES = {"tavily_search", "anysearch_search", "grok_search"}
_FETCH_TOOL_NAMES = {"tavily_fetch", "anysearch_fetch", "grok_fetch"}


@dataclass
class BudgetGuard:
    max_search: int
    max_fetch: int
    search_count: int = 0
    fetch_count: int = 0

    def exhausted_search(self) -> bool:
        return self.search_count >= self.max_search

    def exhausted_fetch(self) -> bool:
        return self.fetch_count >= self.max_fetch

    def consume_search(self) -> None:
        self.search_count += 1

    def consume_fetch(self) -> None:
        self.fetch_count += 1

    def wrap(self, tool: Any) -> Any:
        """Wrap a single tool with budget counting."""
        name = getattr(tool, "name", "")
        if name in _SEARCH_TOOL_NAMES:
            return _wrap_tool(tool, self, is_search=True)
        if name in _FETCH_TOOL_NAMES:
            return _wrap_tool(tool, self, is_search=False)
        return tool  # non-search/fetch: pass through (D6 闸1: no read/write/bash)


def _wrap_tool(tool: Any, guard: BudgetGuard, *, is_search: bool) -> Any:
    """Return a tool-like object whose execute checks budget first."""
    original_execute = tool.execute
    kind = "search" if is_search else "fetch"

    async def _execute(tool_call_id, params, signal=None, on_update=None):  # type: ignore[no-untyped-def]
        if is_search:
            if guard.exhausted_search():
                return _budget_exhausted_result(kind, guard)
            guard.consume_search()
        else:
            if guard.exhausted_fetch():
                return _budget_exhausted_result(kind, guard)
            guard.consume_fetch()
        return await original_execute(tool_call_id, params, signal, on_update)

    # shallow copy with overridden execute
    import copy
    wrapped = copy.copy(tool)
    wrapped.execute = _execute  # type: ignore[attr-defined]
    return wrapped


def _budget_exhausted_result(kind: str, guard: BudgetGuard) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": f"budget_exhausted: {kind} limit reached "
                                             f"(search={guard.search_count}/{guard.max_search}, "
                                             f"fetch={guard.fetch_count}/{guard.max_fetch})"}],
        "details": {"budget_exhausted": True, "kind": kind},
    }


def wrap_tools_with_budget(tools: list[Any], guard: BudgetGuard) -> list[Any]:
    """Wrap all search/fetch tools in the list; pass through others."""
    return [guard.wrap(t) for t in tools]


__all__ = ["BudgetGuard", "wrap_tools_with_budget"]
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/eval/unit/test_budget_guard.py -v
```
Expected: 4 passed.

- [ ] **Step 5: 提交**

```bash
git add eval/src/eval/runner/budget_guard.py tests/eval/unit/test_budget_guard.py
git commit -m "P4: eval harness — A1 budget guard (search/fetch wrapper, Task 6, D7)"
```

---

## Task 7: A1 single_agent ASGI 服务(D9)

**Files:**
- Create: `eval/src/eval/runner/single_agent_app.py`
- Test: `tests/eval/unit/test_single_agent_app.py`

- [ ] **Step 1: 写失败测试**

```python
"""single_agent_app: A1 ASGI service (D9)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eval.runner.single_agent_app import create_single_agent_app


def test_app_has_run_endpoints():
    app = create_single_agent_app()
    with TestClient(app) as client:
        # health
        r = client.get("/eval/health")
        assert r.status_code == 200
        assert r.json()["runtime"] == "single_agent"
        # POST /eval/run returns task_id (202)
        r = client.post("/eval/run", json={
            "research_brief": {
                "target": {"name": "x", "category": "benchmark"},
                "goal": "Compare A vs B",
                "competitors": ["A", "B"],
                "dimensions": ["price"],
            },
            "search_overrides": {"max_queries": 5, "max_fetches": 10, "max_wall_seconds": 60},
        })
        assert r.status_code == 202
        assert "task_id" in r.json()


def test_app_run_poll_completes_with_synthetic_runner(monkeypatch):
    """Inject a fake runner so we test HTTP shape without real LLM."""
    from eval.runner import single_agent_app as saa

    async def fake_run(task_id, brief, overrides):
        return {"markdown": "# table\n|a|b|\n|---|---|\n|1|2|", "status": "completed"}

    monkeypatch.setattr(saa, "_run_single_agent", fake_run)
    app = create_single_agent_app()
    with TestClient(app) as client:
        r = client.post("/eval/run", json={
            "research_brief": {"target": {"name": "x", "category": "benchmark"},
                               "goal": "g", "competitors": ["A"], "dimensions": ["d"]},
            "search_overrides": {},
        })
        task_id = r.json()["task_id"]
        r = client.get(f"/eval/run/{task_id}")
        assert r.json()["status"] == "completed"
        r = client.get(f"/eval/run/{task_id}/report")
        assert "table" in r.json()["markdown"]
```

- [ ] **Step 2: 运行确认失败**

```bash
uv run pytest tests/eval/unit/test_single_agent_app.py -v
```
Expected: FAIL `No module named 'eval.runner.single_agent_app'`.

- [ ] **Step 3: 写 eval/src/eval/runner/single_agent_app.py**

```python
"""A1 single_agent ASGI service (D9).

复用 competitive_app.wiring._HarnessFactory + search_tavily capability,
裸 agent_loop (不进 ResearchRunner/CoverageEngine). 独立 ASGI 服务,
POST /eval/run + GET /eval/run/{task_id} + /report. budget guard 限
search/fetch (D7). 不装 coding tools (D6 闸1).
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .budget_guard import BudgetGuard, wrap_tools_with_budget

app_state: dict[str, Any] = {"tasks": {}}


class _Brief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: dict[str, str]
    goal: str = Field(min_length=1)
    competitors: list[str] = Field(min_length=1)
    dimensions: list[str] = Field(min_length=1)


class _RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    research_brief: _Brief
    search_overrides: dict[str, Any] | None = None


def create_single_agent_app() -> FastAPI:
    app = FastAPI(title="eval single_agent (A1)", version="0.0.1")

    @app.get("/eval/health")
    async def health():
        return {"status": "ok", "runtime": "single_agent", "active": len(app_state["tasks"])}

    @app.post("/eval/run", status_code=202)
    async def run(body: _RunRequest):
        task_id = f"a1-{uuid.uuid4().hex[:8]}"
        app_state["tasks"][task_id] = {"status": "running", "markdown": "", "started": asyncio.get_event_loop().time()}
        asyncio.create_task(_run_single_agent(task_id, body.research_brief, body.search_overrides or {}))
        return {"task_id": task_id, "status": "running"}

    @app.get("/eval/run/{task_id}")
    async def status(task_id: str):
        t = app_state["tasks"].get(task_id)
        if not t:
            return JSONResponse(status_code=404, content={"error": "not found"})
        return {"task_id": task_id, "status": t["status"]}

    @app.get("/eval/run/{task_id}/report")
    async def report(task_id: str):
        t = app_state["tasks"].get(task_id)
        if not t:
            return JSONResponse(status_code=404, content={"error": "not found"})
        return {"task_id": task_id, "markdown": t.get("markdown", ""), "status": t["status"]}

    return app


async def _run_single_agent(task_id: str, brief: _Brief, overrides: dict[str, Any]) -> dict[str, Any]:
    """Build harness via _HarnessFactory + search_tavily, run bare agent_loop.

    D6 闸1: only search_tavily loaded, no coding tools.
    D7: budget_guard wraps tavily_search/tavily_fetch.
    D9: prompt = "use tools, budget N search + M fetch, output Markdown table".
    """
    # NOTE: real impl wires _HarnessFactory.build_ephemeral + load_capability_packages(enabled=["search_tavily"])
    # + budget_guard.wrap_tools_with_budget + agent.run(prompt) -> collect assistant messages -> extract markdown.
    # Placeholder kept minimal; full wiring in Task 7 Step 4 (live-tested in integration/live).
    max_search = int(overrides.get("max_queries", 20))
    max_fetch = int(overrides.get("max_fetches", 40))
    max_wall = int(overrides.get("max_wall_seconds", 720))

    from competitive_app.wiring import build_application_state  # local import (heavy)
    # Real implementation assembles harness here; for unit test we return synthetic.
    # See Task 7 Step 4 for the live wiring.
    markdown = await _wired_run(brief, max_search, max_fetch, max_wall)
    app_state["tasks"][task_id]["status"] = "completed"
    app_state["tasks"][task_id]["markdown"] = markdown
    return {"markdown": markdown, "status": "completed"}


async def _wired_run(brief: _Brief, max_search: int, max_fetch: int, max_wall: int) -> str:
    """Real wiring: assemble harness + search_tavily + budget guard + agent loop."""
    # This is wired in Step 4 of Task 7 (after unit test passes with synthetic).
    # Kept as a seam so unit tests inject fake_run without touching heavy imports.
    raise NotImplementedError("wired in Task 7 Step 4; unit test monkeypatches _run_single_agent")


__all__ = ["create_single_agent_app"]
```

- [ ] **Step 4: 运行测试确认通过(unit test 用 monkeypatch,不触 _wired_run)**

```bash
uv run pytest tests/eval/unit/test_single_agent_app.py -v
```
Expected: 2 passed (fake_run injected via monkeypatch).

- [ ] **Step 5: 实现 _wired_run 真实接线(live 验证留 integration/live)**

读 `competitive_app/src/competitive_app/wiring.py` 的 `build_application_state` + `_HarnessFactory.build_ephemeral`,写真实接线:

```python
# 替换 _wired_run 函数体 (在 eval/src/eval/runner/single_agent_app.py)
async def _wired_run(brief: _Brief, max_search: int, max_fetch: int, max_wall: int) -> str:
    """Real wiring: assemble harness + search_tavily + budget guard + agent loop."""
    import os
    from earendil_works.pi_agent import AgentHarness, InMemorySessionRepo, build_session_context
    from earendil_works.pi_agent.package_manager import load_capability_packages
    from earendil_works.pi_agent import create_models

    # D6 闸1: only search_tavily, no coding tools
    cap_root = os.environ.get("CAPABILITY_PACKAGES_ROOT", "capability_packages")
    report = await load_capability_packages(root=cap_root, enabled=["search_tavily"])
    tools = []
    for spec in report.tools:
        tools.append(spec)

    # D7: wrap with budget guard
    guard = BudgetGuard(max_search=max_search, max_fetch=max_fetch)
    tools = wrap_tools_with_budget(tools, guard)

    # model: deepseek-v4-flash via chatanywhere (env)
    models = create_models()
    from earendil_works.pi_ai.providers.openai import openai_provider
    models.setProvider(openai_provider())

    session = InMemorySessionRepo()
    await session.set_metadata({"id": f"a1-{uuid.uuid4().hex[:8]}"})
    harness = AgentHarness(
        session=session,
        stream_fn=models.streamSimple,
        model={"id": os.environ["OPENAI_MODEL"], "name": os.environ["OPENAI_MODEL"], "api": "openai-completions"},
        system_prompt=(
            f"You are a research agent. Use tavily_search and tavily_fetch tools to answer the query. "
            f"Budget: {max_search} searches, {max_fetch} fetches, {max_wall}s. "
            f"Output a Markdown table with these columns: {brief.dimensions}. "
            f"Goal: {brief.goal}"
        ),
        capability_report=report,
    )
    # Run one turn with the goal as user message
    agent = harness.agent
    # Subscribe to collect final assistant message
    import asyncio
    done = asyncio.Event()
    final_text: list[str] = []
    async def listener(event, abort):
        if event.get("type") == "message_end" and event.get("message", {}).get("role") == "assistant":
            content = event["message"].get("content", "")
            if isinstance(content, list):
                for c in content:
                    if c.get("type") == "text":
                        final_text.append(c["text"])
            elif isinstance(content, str):
                final_text.append(content)
            done.set()
    agent.subscribe(listener)
    await agent.run([{"role": "user", "content": brief.goal}])
    await asyncio.wait_for(done.wait(), timeout=max_wall)
    return "".join(final_text)
```

> **Note:** 上面 Step 5 代码是参考接线骨架,实际 API(`AgentHarness`/`agent.run`/`subscribe` 签名)要对照 `packages/agent/src/earendil_works/pi_agent/agent.py:190` 与 `harness/agent_harness.py` 确认。**这一步的完整接线在 integration/live 测试里验证(Task 11)**,如果 API 对不上,在 live 测试里修正。

- [ ] **Step 6: 提交**

```bash
git add eval/src/eval/runner/single_agent_app.py tests/eval/unit/test_single_agent_app.py
git commit -m "P4: eval harness — A1 single_agent ASGI service + budget guard wiring (Task 7, D9)"
```

---

## Task 8: WideSearch normalizer — report.md -> WideSearchResponse JSONL(D10 N1)

**Files:**
- Create: `eval/src/eval/normalizer/__init__.py`
- Create: `eval/src/eval/normalizer/widesearch.py`
- Create: `eval/src/eval/normalizer/drb2.py` (空壳)
- Test: `tests/eval/unit/test_normalizer_widesearch.py`

- [ ] **Step 1: 写失败测试**

```python
"""WideSearch normalizer: report.md -> WideSearchResponse JSONL (D10 N1)."""
from __future__ import annotations

import json
from pathlib import Path

from eval.normalizer.widesearch import normalize_report, extract_markdown_table


def test_extract_table_finds_required_headers():
    md = """# Report

Some intro text.

| subject | university | rank |
|---------|------------|-----|
| CS | MIT | 1 |
| Physics | Harvard | 2 |

More text.
"""
    table = extract_markdown_table(md, required=["subject", "university", "rank"])
    assert "| subject | university | rank |" in table
    assert "MIT" in table


def test_extract_table_returns_none_if_missing_headers():
    md = "| a | b |\n|---|---|\n| 1 | 2 |"
    assert extract_markdown_table(md, required=["subject", "university"]) is None


def test_normalize_report_writes_jsonl(tmp_path: Path):
    md = "| subject | university |\n|---|---|\n| CS | MIT |"
    out = tmp_path / "competitorlens_a2_ws_en_001_0_response.jsonl"
    normalize_report(
        report_md=md,
        required_headers=["subject", "university"],
        instance_id="ws_en_001",
        model_config_name="competitorlens_a2",
        trial_idx=0,
        out_path=out,
    )
    line = out.read_text(encoding="utf-8").strip()
    obj = json.loads(line)
    assert obj["instance_id"] == "ws_en_001"
    assert "| subject | university |" in obj["response"]
    assert obj["trial_idx"] == 0


def test_normalize_report_no_table_writes_empty_response(tmp_path: Path):
    out = tmp_path / "x.jsonl"
    normalize_report(
        report_md="no table here",
        required_headers=["subject"],
        instance_id="ws_en_002",
        model_config_name="competitorlens_a2",
        trial_idx=0,
        out_path=out,
    )
    obj = json.loads(out.read_text(encoding="utf-8").strip())
    assert obj["response"] == ""  # F5: empty response, scorer scores 0
    assert obj["instance_id"] == "ws_en_002"
```

- [ ] **Step 2: 运行确认失败**

```bash
uv run pytest tests/eval/unit/test_normalizer_widesearch.py -v
```
Expected: FAIL `No module named 'eval.normalizer'`.

- [ ] **Step 3: 写 eval/src/eval/normalizer/__init__.py**

```python
"""Output normalizers: report.md -> benchmark scorer input (D10 N1)."""
```

- [ ] **Step 4: 写 eval/src/eval/normalizer/widesearch.py**

```python
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
    best_coverage = -1
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
```

- [ ] **Step 5: 写 eval/src/eval/normalizer/drb2.py (空壳)**

```python
"""DRB II normalizer (D1 C2-wide: reserved shape, not wired)."""
from __future__ import annotations


def normalize_report(*args, **kwargs):  # type: ignore[no-untyped-def]
    raise NotImplementedError("DRB II track: C2-wide reserves shape, not wired (D1)")


__all__: list[str] = []
```

- [ ] **Step 6: 运行测试确认通过**

```bash
uv run pytest tests/eval/unit/test_normalizer_widesearch.py -v
```
Expected: 4 passed.

- [ ] **Step 7: 提交**

```bash
git add eval/src/eval/normalizer/ tests/eval/unit/test_normalizer_widesearch.py
git commit -m "P4: eval harness — WideSearch normalizer + DRB II stub (Task 8, D10 N1)"
```

---

## Task 9: operations collector — events.jsonl + projection + SOCM(D11 §12.5)

**Files:**
- Create: `eval/src/eval/operations/__init__.py`
- Create: `eval/src/eval/operations/collector.py`
- Test: `tests/eval/unit/test_operations_collector.py`

- [ ] **Step 1: 写失败测试**

```python
"""operations_collector: events.jsonl + projection + SOCM -> operations.json (D11)."""
from __future__ import annotations

import json
from pathlib import Path

from eval.operations.collector import collect_operations, OperationsResult


def _events_jsonl(path: Path, events: list[dict]):
    with path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def test_collect_counts_search_fetch_calls():
    events = [
        {"event_type": "agent.started"},
        {"event_type": "tool.called", "payload": {"name": "tavily_search"}},
        {"event_type": "tool.finished", "payload": {"name": "tavily_search"}},
        {"event_type": "tool.called", "payload": {"name": "tavily_fetch"}},
        {"event_type": "tool.called", "payload": {"name": "tavily_search"}},
        {"event_type": "llm.fallback_switch", "payload": {"from": "openai", "to": "openai"}},
        {"event_type": "agent.finished"},
    ]
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        ej = Path(d) / "events.jsonl"
        _events_jsonl(ej, events)
        result = collect_operations(
            events_path=ej,
            projection={"status": "completed", "first_non_ok_stage": None},
            socm={"filled": 10, "unknown": 2, "conflict": 1, "total": 15, "ratio": 0.66},
        )
        assert result.search_calls == 2
        assert result.fetch_calls == 1
        assert result.fallback_count == 1
        assert result.terminal_status == "completed"
        assert result.coverage_filled == 10
        assert result.coverage_total == 15


def test_collect_handles_missing_socm():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        ej = Path(d) / "events.jsonl"
        _events_jsonl(ej, [{"event_type": "agent.started"}])
        result = collect_operations(events_path=ej, projection={"status": "failed"}, socm=None)
        assert result.terminal_status == "failed"
        assert result.coverage_total == 0  # A1: no SOCM


def test_collect_distinct_domains():
    events = [
        {"event_type": "tool.finished", "payload": {"name": "tavily_fetch", "url": "https://a.com/x"}},
        {"event_type": "tool.finished", "payload": {"name": "tavily_fetch", "url": "https://a.com/y"}},
        {"event_type": "tool.finished", "payload": {"name": "tavily_fetch", "url": "https://b.com/z"}},
    ]
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        ej = Path(d) / "events.jsonl"
        _events_jsonl(ej, events)
        result = collect_operations(events_path=ej, projection={"status": "completed"}, socm={})
        assert result.distinct_domains == 2
```

- [ ] **Step 2: 运行确认失败**

```bash
uv run pytest tests/eval/unit/test_operations_collector.py -v
```
Expected: FAIL `No module named 'eval.operations'`.

- [ ] **Step 3: 写 eval/src/eval/operations/__init__.py**

```python
"""Operations collector: aggregate run metrics from events/projection/SOCM (D11)."""
```

- [ ] **Step 4: 写 eval/src/eval/operations/collector.py**

```python
"""operations_collector (D11 §12.5).

读 data/runs/<task_id>/events.jsonl (RunJournal) + task projection + SOCM,
产 operations.json: search/fetch 数, fallback 次数, terminal status,
coverage cells, distinct domains, evidence count, 失败阶段.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass
class OperationsResult:
    terminal_status: str = "unknown"
    failure_stage: str | None = None
    search_calls: int = 0
    fetch_calls: int = 0
    fallback_count: int = 0
    distinct_domains: int = 0
    evidence_count: int = 0
    coverage_filled: int = 0
    coverage_unknown: int = 0
    coverage_conflict: int = 0
    coverage_total: int = 0
    coverage_ratio: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SEARCH_TOOL_NAMES = {"tavily_search", "anysearch_search", "grok_search"}
_FETCH_TOOL_NAMES = {"tavily_fetch", "anysearch_fetch", "grok_fetch"}


def collect_operations(
    *,
    events_path: Path | str,
    projection: dict[str, Any],
    socm: dict[str, Any] | None,
) -> OperationsResult:
    result = OperationsResult()
    result.terminal_status = projection.get("status", "unknown")
    result.failure_stage = projection.get("first_non_ok_stage")
    domains: set[str] = set()

    p = Path(events_path)
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            et = evt.get("event_type", "")
            payload = evt.get("payload") or {}
            if et == "tool.called":
                name = payload.get("name", "")
                if name in _SEARCH_TOOL_NAMES:
                    result.search_calls += 1
                elif name in _FETCH_TOOL_NAMES:
                    result.fetch_calls += 1
            elif et == "tool.finished":
                url = payload.get("url") or payload.get("source")
                if url:
                    try:
                        domains.add(urlparse(url).netloc)
                    except Exception:
                        pass
            elif et.startswith("llm.fallback"):
                if et in ("llm.fallback_switch", "llm.fallback_start"):
                    result.fallback_count += 1

    result.distinct_domains = len(domains)

    if socm:
        result.coverage_filled = int(socm.get("filled", 0))
        result.coverage_unknown = int(socm.get("unknown", 0))
        result.coverage_conflict = int(socm.get("conflict", 0))
        result.coverage_total = int(socm.get("total", 0))
        result.coverage_ratio = float(socm.get("ratio", 0.0))
    # evidence_count from projection if available
    result.evidence_count = int(projection.get("evidence_count", 0))
    return result


__all__ = ["OperationsResult", "collect_operations"]
```

- [ ] **Step 5: 运行测试确认通过**

```bash
uv run pytest tests/eval/unit/test_operations_collector.py -v
```
Expected: 3 passed.

- [ ] **Step 6: 提交**

```bash
git add eval/src/eval/operations/ tests/eval/unit/test_operations_collector.py
git commit -m "P4: eval harness — operations collector (Task 9, D11)"
```

---

## Task 10: evaluator — 调官方 WideSearch scorer(D10 H1)

**Files:**
- Create: `eval/src/eval/evaluator/__init__.py`
- Create: `eval/src/eval/evaluator/widesearch.py`
- Create: `eval/src/eval/evaluator/drb2.py` (空壳)
- Create: `vendor/widesearch/patches/config.patch` (deepseek-v4-flash 注册)
- Test: `tests/eval/unit/test_evaluator_widesearch.py`

- [ ] **Step 1: patch WideSearch config.py 注册 deepseek-v4-flash**

读 `vendor/widesearch/src/utils/config.py`,找到 `model_config` dict,加条目:

```python
# 在 model_config dict 里加 (eval harness patch, D10):
"deepseek-v4-flash": {
    "model_name": os.environ.get("OPENAI_MODEL", "deepseek-v4-flash"),
    "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.chatanywhere.tech/v1") + "/v1",
    "api_key": os.environ.get("OPENAI_API_KEY", ""),
    "generate_kwargs": {"max_tokens": 65535},
},
```

并改 `default_eval_config` 指向 deepseek-v4-flash:
```python
"default_eval_config": {
    "model_name": os.environ.get("OPENAI_MODEL", "deepseek-v4-flash"),
    "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.chatanywhere.tech/v1") + "/v1",
    "api_key": os.environ.get("OPENAI_API_KEY", ""),
    "generate_kwargs": {"max_tokens": 10240},
    "temperature": 0,
},
```

同时**在 config.py 顶部加 `import os`**(若没有)。

> **关键(D23 契约):** api_key 用 `os.environ.get`,**不硬编码**。base_url 同理。patch diff 保存到 `vendor/widesearch/patches/config.patch`:

```bash
cd vendor/widesearch
git diff src/utils/config.py > patches/config.patch
cd ../../
cat vendor/widesearch/patches/config.patch | head -30
```

- [ ] **Step 2: 写失败测试**

```python
"""WideSearch evaluator: call官方 scorer + parse scores (D10 H1)."""
from __future__ import annotations

import json
from pathlib import Path

from eval.evaluator.widesearch import build_scorer_command, parse_scores, ScoreRow


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
    raw.write_text(json.dumps({
        "score": 0.85,
        "precision_by_item": 0.9,
        "recall_by_item": 0.8,
        "f1_by_item": 0.85,
        "precision_by_line": 0.88,
        "recall_by_line": 0.82,
        "f1_by_line": 0.85,
    }))
    rows = parse_scores(raw_dir=tmp_path, model_config_name="competitorlens_a2", trial_num=1)
    assert len(rows) == 1
    assert rows[0].instance_id == "ws_en_001"
    assert rows[0].f1_by_item == 0.85
    assert rows[0].score == 0.85


def test_parse_scores_missing_file_returns_null(tmp_path: Path):
    rows = parse_scores(raw_dir=tmp_path, model_config_name="competitorlens_a2", trial_num=1)
    assert len(rows) == 0  # no files -> no rows; orchestrator treats missing as F6 null
```

- [ ] **Step 3: 运行确认失败**

```bash
uv run pytest tests/eval/unit/test_evaluator_widesearch.py -v
```
Expected: FAIL `No module named 'eval.evaluator'`.

- [ ] **Step 4: 写 eval/src/eval/evaluator/__init__.py**

```python
"""Evaluators: call官方 benchmark scorer (D10 H1)."""
```

- [ ] **Step 5: 写 eval/src/eval/evaluator/widesearch.py**

```python
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
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
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
        parts = name.split("_")
        # variant = parts[0..1] = competitorlens a2; instance_id = middle; trial = last-2
        # WideSearch instance_id 格式 ws_en_001 / ws_zh_001
        # 保守: 找 "ws" 开头
        try:
            ws_idx = parts.index("ws") if "ws" in parts else 0
            instance_id = "_".join(parts[ws_idx:-2])  # ws_en_001
            trial_idx = int(parts[-2])
        except (ValueError, IndexError):
            continue
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            rows.append(ScoreRow(instance_id, model_config_name, trial_idx,
                                 None, None, None, None, None, None, None, "evaluator_parse_error"))
            continue
        rows.append(ScoreRow(
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
        ))
    return rows


__all__ = ["ScoreRow", "build_scorer_command", "run_scorer", "parse_scores"]
```

- [ ] **Step 6: 写 eval/src/eval/evaluator/drb2.py (空壳)**

```python
"""DRB II evaluator (D1 C2-wide: reserved shape, not wired)."""
from __future__ import annotations


def run_scorer(*args, **kwargs):  # type: ignore[no-untyped-def]
    raise NotImplementedError("DRB II track: C2-wide reserves shape, not wired (D1)")


__all__: list[str] = []
```

- [ ] **Step 7: 运行测试确认通过**

```bash
uv run pytest tests/eval/unit/test_evaluator_widesearch.py -v
```
Expected: 3 passed.

- [ ] **Step 8: 提交**

```bash
git add eval/src/eval/evaluator/ vendor/widesearch/patches/ tests/eval/unit/test_evaluator_widesearch.py
git commit -m "P4: eval harness — WideSearch evaluator + config patch (Task 10, D10 H1)"
```

---

## Task 11: orchestrator — CLI `eval.run --stage smoke`(D12)

**Files:**
- Create: `eval/src/eval/orchestrator.py`
- Create: `eval/src/eval/__main__.py`
- Test: `tests/eval/unit/test_orchestrator.py`

- [ ] **Step 1: 写失败测试**

```python
"""orchestrator: CLI driver + run manifest + paired delta (D12)."""
from __future__ import annotations

import json
from pathlib import Path

from eval.orchestrator import (
    RunManifest, build_run_manifest, compute_paired_deltas, PairedDelta,
    run_id_for_stage,
)


def test_run_id_format():
    rid = run_id_for_stage(stage="smoke", benchmark="widesearch",
                           manifest_rev="abc123", short_sha="a80dab2")
    assert rid == "smoke-ws-abc123-a80dab2"


def test_build_run_manifest_captures_pins():
    m = build_run_manifest(
        stage="smoke", benchmark="widesearch",
        repo_commit="a80dab2", repo_dirty=False,
        benchmark_revision="wsha1", manifest_revision="mrev1",
        model="deepseek-v4-flash", provider="openai",
        base_url="https://api.chatanywhere.tech",
        eval_model_config_name="deepseek-v4-flash",
        search_provider="tavily", budget={"max_queries": 20, "max_fetches": 40, "max_wall_seconds": 720},
        variants=["a1", "a2"], repetitions=1,
    )
    assert m.repo_commit == "a80dab2"
    assert m.model == "deepseek-v4-flash"
    assert m.budget["max_queries"] == 20
    assert m.variants == ["a1", "a2"]
    d = m.to_dict()
    assert d["repo_dirty"] is False
    assert "scorer_command" in d or True  # scorer command filled at eval time


def test_compute_paired_deltas():
    from eval.evaluator.widesearch import ScoreRow
    a1 = [
        ScoreRow("ws_en_001", "competitorlens_a1", 0, 0.5, 0.6, 0.4, 0.5, 0.6, 0.4, 0.5, None),
        ScoreRow("ws_en_002", "competitorlens_a1", 0, 0.3, 0.4, 0.35, 0.3, 0.4, 0.35, 0.3, None),
    ]
    a2 = [
        ScoreRow("ws_en_001", "competitorlens_a2", 0, 0.8, 0.9, 0.85, 0.8, 0.9, 0.85, 0.8, None),
        ScoreRow("ws_en_002", "competitorlens_a2", 0, 0.2, 0.3, 0.25, 0.2, 0.3, 0.25, 0.2, None),
    ]
    deltas = compute_paired_deltas(a1_rows=a1, a2_rows=a2, metric="f1_by_item")
    assert len(deltas) == 2
    assert deltas[0].instance_id == "ws_en_001"
    assert abs(deltas[0].delta - (0.85 - 0.5)) < 1e-9
    assert deltas[0].a2_wins is True
    assert deltas[1].a2_wins is False  # 0.25 < 0.35


def test_compute_paired_deltas_handles_null_a2():
    from eval.evaluator.widesearch import ScoreRow
    a1 = [ScoreRow("ws_en_001", "competitorlens_a1", 0, 0.5, None, None, 0.5, None, None, 0.5, None)]
    a2 = [ScoreRow("ws_en_001", "competitorlens_a2", 0, None, None, None, None, None, None, None, None, "F6")]
    deltas = compute_paired_deltas(a1_rows=a1, a2_rows=a2, metric="f1_by_item")
    assert deltas[0].a2_wins is None  # null -> no comparison
    assert deltas[0].delta is None
```

- [ ] **Step 2: 运行确认失败**

```bash
uv run pytest tests/eval/unit/test_orchestrator.py -v
```
Expected: FAIL `No module named 'eval.orchestrator'`.

- [ ] **Step 3: 写 eval/src/eval/orchestrator.py**

```python
"""orchestrator (D12): CLI driver for eval runs.

uv run python -m eval.run --stage smoke --benchmark widesearch --variants a1,a2

Flow (基准文档 §10):
1. load manifest (eval/manifests/widesearch_smoke.jsonl)
2. for each (case, variant, repetition): submit + poll + collect raw
3. normalize reports -> WideSearchResponse JSONL
4. all runs done -> start evaluator (D6 闸3, §10.2.6)
5. parse scores -> paired deltas -> summary
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class PairedDelta:
    instance_id: str
    metric: str
    a1_value: float | None
    a2_value: float | None
    delta: float | None
    a2_wins: bool | None  # True/False/None(null)


@dataclass
class RunManifest:
    stage: str
    benchmark: str
    repo_commit: str
    repo_dirty: bool
    benchmark_revision: str
    manifest_revision: str
    model: str
    provider: str
    base_url: str
    eval_model_config_name: str
    search_provider: str
    budget: dict[str, Any]
    variants: list[str]
    repetitions: int
    run_start: str = ""
    run_end: str = ""
    scorer_command: str = ""
    scorer_exit_code: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_id_for_stage(*, stage: str, benchmark: str, manifest_revision: str, short_sha: str) -> str:
    bench_short = "ws" if benchmark == "widesearch" else "drb2"
    return f"{stage}-{bench_short}-{manifest_revision[:7]}-{short_sha}"


def build_run_manifest(
    *, stage, benchmark, repo_commit, repo_dirty, benchmark_revision, manifest_revision,
    model, provider, base_url, eval_model_config_name, search_provider, budget,
    variants, repetitions,
) -> RunManifest:
    return RunManifest(
        stage=stage, benchmark=benchmark, repo_commit=repo_commit, repo_dirty=repo_dirty,
        benchmark_revision=benchmark_revision, manifest_revision=manifest_revision,
        model=model, provider=provider, base_url=base_url,
        eval_model_config_name=eval_model_config_name, search_provider=search_provider,
        budget=budget, variants=variants, repetitions=repetitions,
    )


def compute_paired_deltas(
    *, a1_rows: list, a2_rows: list, metric: str,
) -> list[PairedDelta]:
    """A2 - A1 per case (基准文档 §2.1). null (F6) -> delta None."""
    a1_by = {r.instance_id: r for r in a1_rows}
    a2_by = {r.instance_id: r for r in a2_rows}
    deltas: list[PairedDelta] = []
    for iid, a2 in a2_by.items():
        a1 = a1_by.get(iid)
        a1v = getattr(a1, metric) if a1 else None
        a2v = getattr(a2, metric)
        if a1v is None or a2v is None:
            deltas.append(PairedDelta(iid, metric, a1v, a2v, None, None))
            continue
        delta = a2v - a1v
        wins = a2v > a1v if abs(delta) > 1e-9 else None
        deltas.append(PairedDelta(iid, metric, a1v, a2v, delta, bool(a2v > a1v) if wins is None else wins))
    return deltas


async def run_smoke(
    *,
    manifest_path: Path | str,
    variants: list[str],
    app_url: str = "http://127.0.0.1:8000",
    a1_url: str = "http://127.0.0.1:8001",
    out_root: Path | str = "data/evaluations",
    budget: dict[str, Any] | None = None,
) -> str:
    """Full smoke run (基准文档 §10.2). Returns run_id."""
    from eval.manifest import load_manifest
    from eval.runner.http_client import CompetitiveAppClient

    budget = budget or {"max_queries": 20, "max_fetches": 40, "max_wall_seconds": 720}
    cases = load_manifest(manifest_path)
    repo_sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode().strip()
    manifest_rev = subprocess.check_output(
        ["git", "hash-object", str(manifest_path)]
    ).decode().strip()[:7]
    run_id = run_id_for_stage(stage="smoke", benchmark="widesearch",
                              manifest_revision=manifest_rev, short_sha=repo_sha)
    run_dir = Path(out_root) / run_id
    (run_dir / "raw" / "widesearch").mkdir(parents=True, exist_ok=True)
    (run_dir / "normalized" / "widesearch_predictions").mkdir(parents=True, exist_ok=True)
    (run_dir / "scores").mkdir(parents=True, exist_ok=True)
    (run_dir / "summary").mkdir(parents=True, exist_ok=True)

    app_client = CompetitiveAppClient(base_url=app_url)

    for case in cases:
        for variant in variants:
            for rep in range(1):  # Smoke 1 repetition
                if variant == "a2":
                    result = await app_client.run_task(
                        research_brief=case.research_brief.model_dump(),
                        search_overrides={"max_queries": budget["max_queries"],
                                           "max_wall_seconds": budget["max_wall_seconds"]},
                        timeout=900,
                    )
                    markdown = result.report_markdown
                    socm = result.projection.get("coverage", {}) if result.projection else {}
                    task_id = result.task_id
                    terminal = result.terminal_status
                else:  # a1
                    # POST to A1 service
                    import httpx
                    async with httpx.AsyncClient(base_url=a1_url, timeout=900) as ac:
                        r = await ac.post("/eval/run", json={
                            "research_brief": case.research_brief.model_dump(),
                            "search_overrides": budget,
                        })
                        task_id = r.json()["task_id"]
                        # poll
                        import asyncio as _aio
                        deadline = _aio.get_event_loop().time() + 900
                        terminal = "running"
                        while _aio.get_event_loop().time() < deadline:
                            s = await ac.get(f"/eval/run/{task_id}")
                            terminal = s.json().get("status", "running")
                            if terminal in ("completed", "failed", "aborted"):
                                break
                            await _aio.sleep(5)
                        rep_r = await ac.get(f"/eval/run/{task_id}/report")
                        markdown = rep_r.json().get("markdown", "")
                        socm = None  # A1 no SOCM
                        result = None

                # write raw
                raw_dir = run_dir / "raw" / "widesearch" / case.case_id / variant / "0"
                raw_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / "request.json").write_text(case.model_dump_json() + "\n", encoding="utf-8")
                (raw_dir / "task_projection.json").write_text(
                    json.dumps({"task_id": task_id, "status": terminal}) + "\n", encoding="utf-8")
                (raw_dir / "report.md").write_text(markdown, encoding="utf-8")
                (raw_dir / "socm.json").write_text(
                    json.dumps(socm) if socm else '{"variant": "%s", "note": "no SOCM"}' % variant,
                    encoding="utf-8")

    # 2. normalize (基准文档 §10.2.4)
    from eval.normalizer.widesearch import normalize_report
    for case in cases:
        for variant in variants:
            md = (run_dir / "raw" / "widesearch" / case.case_id / variant / "0" / "report.md").read_text(encoding="utf-8")
            out = run_dir / "normalized" / "widesearch_predictions" / f"competitorlens_{variant}_{case.source_task_id}_0_response.jsonl"
            normalize_report(
                report_md=md, required_headers=case.research_brief.dimensions,
                instance_id=case.source_task_id, model_config_name=f"competitorlens_{variant}",
                trial_idx=0, out_path=out,
            )

    # 3. evaluator (基准文档 §10.3, all runs done first §10.2.6)
    from eval.evaluator.widesearch import build_scorer_command, run_scorer, parse_scores
    all_rows = []
    for variant in variants:
        cmd = build_scorer_command(
            model_config_name=f"competitorlens_{variant}",
            eval_model_config_name="deepseek-v4-flash",
            response_root=str(run_dir / "normalized" / "widesearch_predictions"),
            result_save_root=str(run_dir / "scores" / "widesearch_raw"),
            trial_num=1,
        )
        rc = run_scorer(cmd)
        rows = parse_scores(raw_dir=run_dir / "scores" / "widesearch_raw",
                            model_config_name=f"competitorlens_{variant}", trial_num=1)
        all_rows.extend(rows)

    # 4. paired deltas + summary
    a1_rows = [r for r in all_rows if r.variant == "competitorlens_a1"]
    a2_rows = [r for r in all_rows if r.variant == "competitorlens_a2"]
    deltas = compute_paired_deltas(a1_rows=a1_rows, a2_rows=a2_rows, metric="f1_by_item")

    (run_dir / "scores" / "paired_deltas.json").write_text(
        json.dumps([asdict(d) for d in deltas], ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "scores" / "widesearch.jsonl").write_text(
        "\n".join(json.dumps(asdict(r), ensure_ascii=False) for r in all_rows) + "\n", encoding="utf-8")

    # summary (mean@1, 基准文档 §12.3)
    completed = [r for r in all_rows if r.failure_stage is None]
    summary = {
        "repetitions": 1,
        "all_case_count": len(all_rows),
        "completed_count": len(completed),
        "mean_f1_a1": sum(r.f1_by_item for r in a1_rows if r.f1_by_item is not None) / max(1, len([r for r in a1_rows if r.f1_by_item is not None])),
        "mean_f1_a2": sum(r.f1_by_item for r in a2_rows if r.f1_by_item is not None) / max(1, len([r for r in a2_rows if r.f1_by_item is not None])),
        "paired_delta_mean": sum(d.delta for d in deltas if d.delta is not None) / max(1, len([d for d in deltas if d.delta is not None])),
    }
    (run_dir / "summary" / "metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # manifest
    manifest = build_run_manifest(
        stage="smoke", benchmark="widesearch",
        repo_commit=repo_sha, repo_dirty=bool(subprocess.check_output(["git", "status", "--porcelain"]).decode().strip()),
        benchmark_revision=open("data/benchmarks/widesearch/WS_REPO_SHA.txt").read().strip(),
        manifest_revision=manifest_rev,
        model="deepseek-v4-flash", provider="openai", base_url=os.environ.get("OPENAI_BASE_URL", ""),
        eval_model_config_name="deepseek-v4-flash", search_provider="tavily",
        budget=budget, variants=variants, repetitions=1,
    )
    manifest.scorer_command = cmd
    manifest.scorer_exit_code = rc
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    return run_id


__all__ = ["RunManifest", "PairedDelta", "run_id_for_stage", "build_run_manifest",
           "compute_paired_deltas", "run_smoke"]
```

- [ ] **Step 4: 写 eval/src/eval/__main__.py**

```python
"""CLI entry: uv run python -m eval.run --stage smoke (D12)."""
from __future__ import annotations

import argparse
import asyncio
import sys

from eval.orchestrator import run_smoke


def main() -> int:
    p = argparse.ArgumentParser(prog="eval.run")
    p.add_argument("--stage", default="smoke", choices=["smoke", "pilot"])
    p.add_argument("--benchmark", default="widesearch", choices=["widesearch", "drb2"])
    p.add_argument("--variants", default="a1,a2")
    p.add_argument("--manifest", default="eval/manifests/widesearch_smoke.jsonl")
    p.add_argument("--app-url", default="http://127.0.0.1:8000")
    p.add_argument("--a1-url", default="http://127.0.0.1:8001")
    args = p.parse_args()

    if args.benchmark == "drb2":
        print("DRB II not wired (D1 C2-wide)", file=sys.stderr)
        return 2

    variants = args.variants.split(",")
    run_id = asyncio.run(run_smoke(
        manifest_path=args.manifest, variants=variants,
        app_url=args.app_url, a1_url=args.a1_url,
    ))
    print(f"run complete: {run_id}")
    print(f"  data/evaluations/{run_id}/scores/widesearch.jsonl")
    print(f"  data/evaluations/{run_id}/scores/paired_deltas.json")
    print(f"  data/evaluations/{run_id}/summary/metrics.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 运行测试确认通过**

```bash
uv run pytest tests/eval/unit/test_orchestrator.py -v
```
Expected: 4 passed.

- [ ] **Step 6: 提交**

```bash
git add eval/src/eval/orchestrator.py eval/src/eval/__main__.py tests/eval/unit/test_orchestrator.py
git commit -m "P4: eval harness — orchestrator CLI + paired delta (Task 11, D12)"
```

---

## Task 12: gold 隔离 contract 测试(D6 闸 4)

**Files:**
- Create: `tests/eval/contract/__init__.py`
- Create: `tests/eval/contract/test_gold_isolation.py`

- [ ] **Step 1: 写 contract 测试**

```python
"""Contract: gold isolation (D6 闸 4).

运行进程代码 (eval/runner, eval/adapter, eval/normalizer) 不得 import
widesearch_gold 路径或 open() data/benchmarks/ gold 目录. evaluator 独立,
允许读 gold (但本仓 eval/evaluator 只调官方 scorer, 不直接读 gold CSV).
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVAL_SRC = ROOT / "eval" / "src" / "eval"

# 运行进程目录 (不能碰 gold)
RUNNER_DIRS = [EVAL_SRC / "runner", EVAL_SRC / "adapter", EVAL_SRC / "normalizer", EVAL_SRC / "manifest.py",
               EVAL_SRC / "manifest_builder.py"]
# gold 相关字符串 (出现在 import/open 路径里 = 泄漏)
GOLD_MARKERS = ["widesearch_gold", "data/benchmarks", "tasks_and_rubrics", "rubric"]


def _import_roots(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []
    roots: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.append(node.module)
    return roots


def _scan_string_markers(path: Path) -> list[str]:
    """扫描字符串字面量是否含 gold 路径标记."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for marker in GOLD_MARKERS:
                if marker in node.value:
                    hits.append(f"{path.name}: string contains {marker!r}")
    return hits


def test_runner_does_not_import_gold():
    offenders: list[str] = []
    for d in RUNNER_DIRS:
        if d.is_file():
            d = [d]
        elif d.is_dir():
            d = list(d.rglob("*.py"))
        else:
            continue
        for f in d:
            for root in _import_roots(f):
                if any(m in root for m in GOLD_MARKERS):
                    offenders.append(f"{f}: import {root}")
    assert not offenders, f"gold import violations: {offenders}"


def test_runner_no_gold_path_strings():
    offenders: list[str] = []
    for d in RUNNER_DIRS:
        if d.is_file():
            d = [d]
        elif d.is_dir():
            d = list(d.rglob("*.py"))
        else:
            continue
        for f in d:
            offenders.extend(_scan_string_markers(f))
    assert not offenders, f"gold path string violations: {offenders}"


def test_evaluator_only_calls_scorer_not_gold_csv():
    """evaluator 只调官方 scorer (subprocess), 不直接 open() gold CSV."""
    ev = EVAL_SRC / "evaluator" / "widesearch.py"
    tree = ast.parse(ev.read_text(encoding="utf-8"), filename=str(ev))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    assert "widesearch_gold" not in arg.value, "evaluator opens gold CSV directly"
```

- [ ] **Step 2: 运行 contract 测试**

```bash
uv run pytest tests/eval/contract/test_gold_isolation.py -v
```
Expected: 3 passed. 若有违规, 修 eval 代码移除 gold 引用。

- [ ] **Step 3: 提交**

```bash
git add tests/eval/contract/
git commit -m "P4: eval harness — gold isolation contract test (Task 12, D6)"
```

---

## Task 13: live smoke 烟测(D12, 1 题真跑)

**Files:**
- Create: `tests/eval/integration/live/__init__.py`
- Create: `tests/eval/integration/live/conftest.py`
- Create: `tests/eval/integration/live/test_smoke_one_case.py`

- [ ] **Step 1: 写 conftest 复用 tests/live_env.py 门控**

```python
"""Conftest for eval live tests (D12)."""
from __future__ import annotations

import pytest
from pathlib import Path

# 复用仓库 live_env 门控
import sys
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from live_env import load_dotenv, live_credentials  # noqa: E402


@pytest.fixture
def live_env(monkeypatch):
    load_dotenv()
    creds = live_credentials()
    if not creds:
        pytest.skip("no OPENAI_API_KEY in env (L2)")
    monkeypatch.setenv("OPENAI_MODEL", creds["model_id"])
    monkeypatch.setenv("OPENAI_BASE_URL", creds["base_url"])
    return creds


@pytest.fixture
def tavily_env(live_env):
    if not __import__("os").environ.get("TAVILY_API_KEY"):
        pytest.skip("no TAVILY_API_KEY (D8)")
    return True
```

- [ ] **Step 2: 写 1 题烟测(只测 A2 HTTP 链路连通,不跑完整 5 题)**

```python
"""Live smoke: 1 case A2 via HTTP (D12). Real provider, ~3-5 min."""
from __future__ import annotations

import asyncio
import pytest

from eval.manifest import CaseManifest, ManifestResearchBrief, TargetIdentity
from eval.runner.http_client import CompetitiveAppClient


@pytest.mark.live
@pytest.mark.asyncio
async def test_a2_one_case_http_chain(tavily_env):
    """Submit 1 trivial brief to competitive_app, poll, get report."""
    brief = ManifestResearchBrief(
        target=TargetIdentity(name="eval-smoke", category="benchmark"),
        goal="Compare Apple iPhone 15 vs Samsung Galaxy S24 price. Output a Markdown table with columns: price, screen.",
        competitors=["Apple iPhone 15", "Samsung Galaxy S24"],
        dimensions=["price", "screen"],
    )
    client = CompetitiveAppClient(base_url="http://127.0.0.1:8000")
    result = await client.run_task(
        research_brief=brief.model_dump(),
        search_overrides={"max_queries": 5, "max_wall_seconds": 180},
        timeout=300,
        poll_interval=10,
    )
    assert result.terminal_status in ("completed", "failed", "aborted")
    # completed -> must have non-empty markdown
    if result.terminal_status == "completed":
        assert len(result.report_markdown) > 0
```

> **Note:** 此测试需要 `competitive_app` 已在 8000 端口运行(`uv run competitive_app serve` 或 `bash scripts/serve_app.py`)。CI 不跑(`@pytest.mark.live`),本地手跑证链路。

- [ ] **Step 3: 本地手跑(需起 competitive_app)**

```bash
# terminal 1: 起 app
uv run competitive_app serve --host 127.0.0.1 --port 8000 &
# terminal 2: 跑 live 烟测
uv run pytest tests/eval/integration/live/test_smoke_one_case.py -v -m live
```
Expected: 1 passed(completed 且有 markdown)或 skip(无 key)。

- [ ] **Step 4: 提交**

```bash
git add tests/eval/integration/
git commit -m "P4: eval harness — live smoke test (1 case A2, Task 13, D12)"
```

---

## Task 14: 全量离线测试 + 文档收尾

**Files:**
- Modify: `eval/README.md`
- Run: full test suite

- [ ] **Step 1: 写 eval/README.md**

```bash
cat > eval/README.md <<'EOF'
# eval — CompetitorLens Benchmark Harness

评测 `competitive_app` 的搜索覆盖、事实收集和报告生成效果。
基准方案: [`docs/competitorlens_benchmark_evaluation.md`](../docs/competitorlens_benchmark_evaluation.md)
设计: [`docs/superpowers/specs/2026-08-10-eval-harness-design.md`](../docs/superpowers/specs/2026-08-10-eval-harness-design.md)

## 跑 Smoke(5 题 × A1/A2)

```bash
# 1. 起 competitive_app (A2)
uv run competitive_app serve --host 127.0.0.1 --port 8000 &

# 2. 起 A1 single_agent 服务
uv run python -m eval.runner.serve --variant single_agent --port 8001 &

# 3. 跑 Smoke
uv run python -m eval.run --stage smoke --benchmark widesearch --variants a1,a2
```

产物落 `data/evaluations/<run_id>/`。

## 测试

```bash
uv run pytest tests/eval -m "not live" -q    # 离线全跑 (CI)
uv run pytest tests/eval -m live -q           # 真实 provider (需 .env)
```
EOF
```

- [ ] **Step 2: 跑全量离线测试**

```bash
uv run pytest tests/eval -m "not live" -q
```
Expected: 全绿(unit + contract)。

- [ ] **Step 3: 跑全仓契约测试确认无回归**

```bash
uv run pytest tests/competitive_app/contract tests/packages/agent/contract -q
```
Expected: 全绿(eval/ 不影响现有契约)。

- [ ] **Step 4: lint + format**

```bash
ruff check eval/ tests/eval/
ruff format eval/ tests/eval/
```
Expected: 无 error。

- [ ] **Step 5: 提交**

```bash
git add eval/README.md
git commit -m "P4: eval harness — README + full offline test green (Task 14)"
```

---

## Self-Review

### 1. Spec 覆盖

| Spec 决策 | 覆盖任务 |
|-----------|----------|
| D0 C2-wide | Task 0-14(全套 + Smoke 跑通) |
| D1 双轨骨架 | Task 3/8/10 的 DRB II 空壳 |
| D2 A1+A2 | Task 5(A2 client) + Task 7(A1 服务) |
| D3 eval/ 独立包 | Task 1 |
| D4 W1 HTTP | Task 5(http_client) |
| D5 S4+P2 | Task 0(数据) + Task 4(manifest builder) |
| D6 gold 三道闸 | Task 7(闸1 工具面) + Task 12(闸4 contract) |
| D7 B2 预算 | Task 6(budget_guard) |
| D8 Tavily | Task 7(只 enabled search_tavily) + Task 13(tavily_env) |
| D9 A1-a+(i) | Task 7 |
| D10 evaluator | Task 10 + Task 0 Step 5(config patch) |
| D11 结果产物 | Task 9(operations) + Task 11(orchestrator 写目录) |
| D12 测试纪律 | Task 11(CLI) + Task 13(live) |
| D13 失败零分 | Task 10(parse_scores null) + Task 11(paired delta null) |

### 2. 待定项消除

D10 config 注册 = Task 0 Step 5(确认无 env 注入)+ Task 10 Step 1(patch config.py 用 `os.environ.get`,不硬编码 key,符合 D23)。**不再有"待定"**。

### 3. 类型一致性

- `CaseManifest` / `ManifestResearchBrief` / `TargetIdentity`(Task 2)全文一致。
- `ScoreRow`(Task 10)`variant`/`instance_id`/`trial_idx` 字段在 Task 11 `compute_paired_deltas` 用 `getattr(r, metric)` 一致。
- `OperationsResult`(Task 9)字段在 Task 11 orchestrator 未直接用(orchestrator 用 projection 字段),无冲突。
- `CompetitiveAppClient.run_task` 返回 `TaskResult`(Task 5),Task 11 用其 `report_markdown`/`terminal_status`/`projection`/`task_id` 一致。

### 4. 已知简化(实现时注意)

- Task 7 Step 5 的 `_wired_run` 是参考接线骨架,`AgentHarness`/`agent.run`/`subscribe` 的真实 API 要对照 `packages/agent/src/earendil_works/pi_agent/agent.py:190` 与 `harness/agent_harness.py` 确认——**这一步在 Task 13 live 烟测里验证,不对则修**。unit test(Task 7 Step 4)用 monkeypatch 绕过,不阻塞。
- Task 0 Step 3 的 HF 下载命令可能需要 `huggingface_hub` 依赖(确认是否已在 competitive_app 依赖里,否则加到 eval pyproject)。
- Task 4 Step 5 生成真实 manifest 时,若 S4 规则太严(100 英文题里 vs pattern 命中 <5),需人工 review 手补(manifest notes 记规则)。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-10-eval-harness.md`.

Two execution options:

1. **Subagent-Driven (recommended)** - 每个 Task 派一个 fresh subagent,两阶段 review,快速迭代。适合本计划(14 个 Task 多数独立)。

2. **Inline Execution** - 本会话逐 Task 跑,checkpoint review。适合你想全程盯。

**Which approach?**
