# A2（competitorlens）vs Claude Code — DRB II 对比实验

| 字段 | 值 |
|------|-----|
| **updated** | 2026-08-22 |
| **实验范围** | DRB II（DeepResearch Bench II）5-case smoke（drb2_4/6/18/22/30） |
| **对比对象** | A2 = competitive_app 完整链路（plan→CoverageEngine search→write 三阶段编排） vs Claude Code（headless `claude -p` agentic 研究） |
| **模型** | **A2 与 Claude Code 均基于 deepseek 模型运行**（Claude Code 侧为 `deepseek-v4-flash[1m]`） |
| **judge** | **gpt-5.6-luna** rubric LLM judge（与 A2 基线同一 judge） |
| **判分方式** | 10 份报告（5 A2 + 5 cc）**同一 judge pass、全量 rubric、全报告可见（cap=0）**，并发 5 |

## 摘要

在**同一 deepseek 模型、同一 gpt-5.6-luna judge、同一判分条件**下，A2 以 **mean total 0.350 > Claude Code 0.205**，5/5 case 总分领先，实现增益 **+0.145**。

- **info_recall 打平**：A2 0.137 vs cc 0.138（Δ +0.001）——两个系统检索出的 rubric 精确条目水平相当
- **analysis**：A2 0.365 vs cc 0.206（Δ −0.159）
- **presentation**：A2 0.548 vs cc 0.271（Δ −0.277）

## 1. 目的与方法

DRB II（arXiv:2601.08536）是长文研究报告题，LLM judge 对二元 rubric 逐条判分（三维度 recall / analysis / presentation，总分 = 均值）。本实验回答：**同一个 deepseek 模型下，A2 的竞争情报编排 vs Claude Code 的 agentic 研究循环，谁产出更符合 rubric 的报告。**

| 组 | 是什么 | 怎么跑 |
|---|---|---|
| A2 | competitive_app 完整链路：plan（coverage schema/SOCM）→ CoverageEngine 迭代搜索 → 分节 write | 已有 5-case 报告 |
| cc | Claude Code headless：`claude -p` + WebSearch/WebFetch，一次 prompt 自己搜+写 | 每 case 独立进程，预算上限 $10，`deepseek-v4-flash[1m]` |

**判分**：把 A2 与 cc 的报告放进同一 judge pass，**全量 rubric、cap=0 全报告可见**（harness 默认截断 12000 字符会系统性低估长报告——见 §4.2）。judge 模型 gpt-5.6-luna，与 A2 基线同模型。**方法可信度**：同 pass 重判的 A2 分数精确复现文档基线（drb2_22 total 0.542 / analysis 0.769 / presentation 0.857；drb2_18 0.434；drb2_30 0.258），说明两系统在同一把尺子上。

## 2. 结果（同 pass、全可见、全量 rubric）

### 2.1 逐 case

| case | A2 recall | cc recall | A2 analysis | cc analysis | A2 pres | cc pres | **A2 total** | **cc total** | Δ (cc−A2) |
|---|---|---|---|---|---|---|---|---|---|
| drb2_4 | 0.094 | 0.094 | 0.182 | 0.000 | 0.125 | 0.000 | 0.134 | 0.031 | −0.102 |
| drb2_6 | 0.281 | 0.203 | 0.308 | 0.077 | 0.556 | 0.333 | 0.381 | 0.204 | −0.177 |
| drb2_18 | 0.120 | **0.220** | 0.182 | 0.182 | 1.000 | 0.250 | 0.434 | 0.217 | −0.217 |
| drb2_22 | 0.000 | 0.000 | 0.769 | 0.538 | 0.857 | 0.571 | 0.542 | 0.370 | −0.172 |
| drb2_30 | 0.190 | 0.172 | 0.385 | 0.231 | 0.200 | 0.200 | 0.258 | 0.201 | −0.057 |

### 2.2 维度均值

| 维度 | A2 | cc | Δ (cc−A2) |
|---|---|---|---|
| info_recall | 0.137 | **0.138** | +0.001 |
| analysis | **0.365** | 0.206 | −0.159 |
| presentation | **0.548** | 0.271 | −0.277 |
| **total** | **0.350** | 0.205 | **−0.145** |

### 2.3 cc 运行画像（deepseek-v4-flash[1m]）

| case | turns | WebSearch | cost | wall | 报告 |
|---|---|---|---|---|---|
| drb2_4 | 28 | 25 | $3.90 | 480s | 39,210 chars |
| drb2_6 | 34 | 21 | $3.34 | 419s | 43,350 chars |
| drb2_18 | 26 | 18 | $3.08 | 295s | 30,791 chars |
| drb2_22 | 14 | 13 | $1.77 | 262s | 18,692 chars |
| drb2_30 | 21 | 16 | $2.90 | 263s | 31,038 chars |

（A2 侧运行画像见基准文档 §4.6：每 case ~130-190 搜索 / 50-155 fetch / 600-940s。）

## 3. 关键发现

1. **recall 打平是真信号**：cc 的 WebSearch 检索出的 rubric 精确条目与 A2 的 CoverageEngine 相当（0.138 vs 0.137）。recall 是 DRB II 最难维度（官方最强 GPT-o3 DR 也仅 ~40%），两系统都卡在 0.14 量级，是搜索基建天花板而非编排差异。
2. **A2 领先在 analysis + presentation**：cc 在分析深度（flash 模型的综合论证较弱）和精确格式遵循（表格/章节 exact-match）上落后，两者正是 rubric 用 LLM judge 衡量的核心。
3. **报告质量本身高**：cc 报告 30-43K 字、34-65 条真实来源、17-31 个域名、blocked-reference 规则零违规、不硬编数值（drb2_22 成本表对无数值研究诚实标注"no single USD total"）。输在 rubric 的"分析深度 + 格式贴合"，不是"没研究"。

## 4. 方法论备注

### 4.1 judge 截断问题（harness 级发现）

harness 的 DRB II judge 把报告截断到前 **12000 字符**（`evaluator/drb2.py::_judge_prompt`）。本实验 cc 报告 18-43K 字、A2 报告 14-61K 字，**全部超线**——长报告的分析部分会被系统性裁掉，且"报告越长越吃亏"。本实验用 `--judge-cap 0`（全报告可见）重判规避。**该截断是 harness 的潜在缺陷，建议后续将 judge 输入改为分块或提高上限。**

### 4.2 单 case 冒烟 vs 同 pass

- 12K 截断下的单 case 冒烟（drb2_22）给 cc 0.282-0.344，同 pass 全可见给 0.370——截断压低长报告约 0.1，方向一致。
- **结论以同 pass 全可见（§2）为准**。

## 5. 结论

同一个 deepseek 模型下：
- **A2 编排 > Claude Code agentic 循环**（总分 0.350 vs 0.205，5/5 胜），领先主要来自 analysis 与 presentation。
- **检索召回相当**（recall 打平），搜索基建是共同短板。
- 若目标是提升 cc 侧，方向是：换更强模型（分析深度）或加"按 rubric 精确结构出表"的引导（presentation）。

## 6. 复现

```bash
# 环境（WSL，真实环境）
export PYTHONPATH=$PWD/competitive_app/src:$PWD/packages/agent/src:$PWD/packages/ai/src:$PWD/eval/src
set -a; . ./.env; set +a

# 1) cc 5-case 冒烟（headless claude -p，deepseek-v4-flash[1m]，$10/case 上限）
./.venv/bin/python scripts/cc_drb2_smoke.py \
  --cases drb2_4,drb2_6,drb2_18,drb2_22,drb2_30 --budget-usd 10.0
#   产物 → data/evaluations/cc-smoke-drb2-cc-f896509/

# 2) 同 pass 全可见重判（A2 基线报告 + cc 报告，同一 judge pass）
./.venv/bin/python scripts/cc_vs_a2_samepass.py \
  --cc-run data/evaluations/cc-smoke-drb2-cc-f896509 \
  --a2-run data/evaluations/smoke-drb2-1962711-f896509 \
  --judge-cap 0 --concurrency 5
#   产物 → data/evaluations/cc-vs-a2-samepass-f896509/
```

- judge 模型：`.env` 的 `OPENAI_MODEL`（gpt-5.6-luna，网关 pro3.o0n0o.cc）
- A2 基线报告来源：`data/evaluations/smoke-drb2-1962711-f896509/`
- 脚本：`scripts/cc_drb2_smoke.py`、`scripts/cc_vs_a2_samepass.py`（一次性实验，未集成进 harness）
