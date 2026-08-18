# Eval Harness 运行指标修复进展

| 字段 | 值 |
|------|-----|
| **updated** | 2026-08-18 |
| **branch** | `p4/eval-harness-widesearch-smoke` |
| **commits** | `dfd00f7`/`ebf6637`/`d6fa1df`（指标端到端）→ `fbb7cd4`（9 指标/coverage 修复）→ `6ef385e`/`3e3c8a3`（DRB II pipeline + smoke fixes）→ `5ad7afd`（write 结构跟随）|
| **范围** | 基准文档 §7 运行指标 + A1/A2 双 variant + coverage 填充质量 + DRB II 报告轨 |
| **状态** | **双轨全通**：WideSearch（scorer judge 修复）+ DRB II（pipeline + write 结构跟随）。Live 验证完成：A1 全量 judge total 0.26（analysis 0.77）；A2 结构跟随生效（presentation 0→0.67）|

---

## 1. 目的

`docs/competitorlens_benchmark_evaluation.md`（v0.1.0）定义了 WideSearch + DRB II 双轨评测。本轮目标：**把文档 §7 中"字段在但采集不到 / A1 显示 0"的运行指标全部补上**，并**让 A2（competitive_app 完整链路）+ A1 真正跑通**，使 coverage、A2-A1 配对 delta、WideSearch F1 等核心指标可测且**数值真实**。

## 2. 已完成的工作

### 2.1 已提交的 3 个 commit（指标端到端 + A2 跑通）

- **`dfd00f7`** — A1 仪表化（RunJournal/EvalJournalStream/subtask 包装）+ collector 指标 + orchestrator 聚合 + scorer PYTHONPATH + pyyaml
- **`ebf6637`** — A2 search wall-clock 截止（`Budget.consume_wall` 是死代码 → 引擎记 deadline，搜索 120s 自终止）
- **`d6fa1df`** — A2 stream sanitize + 有界 sub-agent 取消

### 2.2 本轮新增 9 个修复（`fbb7cd4` 已提交）

#### ① coverage 填充质量（4 个，前面会话定位后实现）

| # | 修复 | 文件 | 效果 |
|---|---|---|---|
| 1 | **subtask 轮转调度** — 每轮每实体至少 1 个 subtask，大实体不再独占全部并行槽 | `coverage_engine.py::_build_subtasks` | 120s wall 内所有实体都能被搜到 |
| 2 | **UNKNOWN 格可重填** — judge 目标集从仅 EMPTY 扩到 EMPTY+UNKNOWN | `extraction.py::_extract_entity` | 修"重搜 UNKNOWN 格永远填不上"的死胡同 |
| 3 | **plan prompt 实体粒度** — 枚举型 brief 拆到条目级，不产聚合行 | `profiles.py::_PLAN_PROMPT` | 修 target-as-聚合行导致的全格 CONFLICT |
| 4 | **逐字引用放宽** — 空白/大小写归一化后包含匹配（"8 GB"↔"8GB"） | `extraction.py::_excerpt_supported` | 深水区 judge 引用渲染差异不再误杀 |

#### ② 三个"F1=0 根因"修复（本轮 smoke 结果分析发现）

| # | 修复 | 文件 | 根因 |
|---|---|---|---|
| 5 | **A1 baseUrl 用网关** — catalog 模型 dict 覆盖 `OPENAI_BASE_URL` | `eval/runner/single_agent_app.py::_resolve_openai_model` | A1 用 catalog 硬编码 `api.openai.com` → 网关 key 401 → 空报告（A1 全 0） |
| 6 | **scorer judge base_url 不重复 /v1** | `vendor/widesearch/src/utils/config.py` | `.env` 的 `OPENAI_BASE_URL` 已含 `/v1`，config 又拼一个 → `/v1/v1/...` 404 |
| 7 | **scorer judge 用普通 OpenAI 客户端** | `vendor/widesearch/src/utils/llm.py` | `AzureOpenAI` 拼 Azure 路径，网关不提供 → 404/HTML；**judge 从未工作过** |
| 8 | **collector duration 用 stage 窗口** | `eval/operations/collector.py` | A2 journal 被后续 task 的 harness 事件污染（min/max 跨 1393s）；stage 事件窗口才是真实 250-320s |

#### ③ A2 journal 污染观察（记录，未根因修复）

A2 观测层存在 journal 交叉写入：每个 case 的 `data/runs/<task_id>/events.jsonl` 结尾会多出 ~100 条 `agent.started/llm.request/llm.response/agent.finished`（带 `run_id`、**无 usage**、**无 tool 事件**）。影响仅 `duration_seconds`（已被 ⑧ 修复规避）；tokens/search/fetch/coverage 均不受污染。疑似 `journal_bridge.py` 的 extension factory **闭包捕获 journal**（`make_journal_extension_factory(journal)`）而非事件时解析 ContextVar。

### 2.3 DRB II 报告轨 pipeline（`6ef385e`）

DeepResearch Bench II（`imlrz/DeepResearch-Bench-II`，arXiv:2601.08536）：132 题由 LLM judge 对二元打分项逐条判分，三维度（信息召回 / 分析 / 表达）得分 = 通过比例，总分 = 三维度均值。实现：

| 组件 | 说明 |
|---|---|
| 数据集 | `data/benchmarks/drb2/tasks_and_rubrics.jsonl`（132 题，gitignored）+ `REVISION.txt`（tracked）。许可证：129×CC BY、idx 26/110×CC BY-NC（商业 manifest 排除）、idx 119×CC0 |
| manifest | `eval/manifests/drb2_smoke.jsonl`（5 英文题：drb2_4/6/18/22/30）；ResearchBrief 只取 prompt，打分内容绝不进运行进程 |
| adapter | `adapter/drb2.py` — 数据集行 → CaseManifest（dev 助手；gold 隔离契约通过）|
| normalizer | `normalizer/drb2.py` — 报告 → UTF-8 `.md`（只做编码/文件名规范化，§10.2.5）|
| evaluator | `evaluator/drb2.py` — **rubric LLM-judge**：逐条 {1,0,-1}+reason+evidence → 三维度比例 → 均值总分。judge 走 pi_ai（env 配置模型），`judge_fn` 可注入（离线单测）|
| orchestrator | `run_smoke` 加 `benchmark` 参数 + drb2 分支（目录/评分/汇总/synthesize 泛化为 row_factory）；`__main__.py` 解除 `--benchmark drb2` 闸门 |
| smoke 限速 | `DRB2_MAX_ITEMS` env：每维度最多 judge 条数（0/缺省 = 全部）|

**运行**：`uv run python -m eval --stage smoke --benchmark drb2 --variants a1,a2`（服务 :8000/:8001 需先起；`DRB2_MAX_ITEMS=3` 可小规模冒烟）。产物 `scores/drb2.jsonl`（每 case 三维度 + total）、`scores/paired_deltas.json`（total 的 A2-A1 delta）、`summary/metrics.json`（mean_total_a1/a2 + 三维度均值）。

**验证**：18 个新单测 + gold 隔离契约绿（Windows 75 / WSL 70 passed）；离线端到端 mock judge 5 case 全出分；Live 小规模验证见 §4。

### 2.4 write 阶段结构跟随（`5ad7afd`，DRB II 报告轨关键）

**根因**（live DRB II smoke 发现）：A2 报告用通用 overview/dims/conclusion 结构，但 DRB II rubric 检查 brief **精确指定的章节/表格**（如 "Cost Data Compilation for Different Vehicle Models" 表）→ 结构依赖的 rubric 全 0。

**修复**（v0.2.10）— 章节选择按优先级：
1. plan 的 `report_structure`（plan prompt 新增字段，planner 从 brief 逐字提取要求章节；live 验证 gpt-5.6-luna 能产出）
2. **程序化兜底** `_extract_report_structure_from_brief`：从 brief 提取编号的 `**粗体标题**` 章节（确定性——plan LLM 有时漏报）
3. 通用 overview/dims/conclusion（保留）

**Live 验证**（drb2_22）：A2 报告现含 `## Cost Data Compilation for Different Vehicle Models`（真实表格）+ `## Summary of Incentive Policies by Country` + `## Comprehensive Analysis`；presentation 采样 0.0 → **0.667**。

### 2.5 DRB II judge 单条调用超时（未 commit）

full judge 实测：单条 judge 调用无超时，网关偶发挂起会阻塞整个打分（7 分钟卡死）。`evaluator/drb2.py` 加 `_JUDGE_CALL_TIMEOUT_S = 60.0`（`asyncio.wait_for`，失败按未提及计）。**待 commit**。

## 3. 指标可测性现状

### ✅ 能测（修复后有真实值）

| 指标 | 实证 |
|---|---|
| WideSearch Item P/R/F1 | **scorer judge 修复后可用**（修复前 judge 404 → 全 0）——重跑验证中 |
| WideSearch Row P/R/F1 | 同上 |
| 逐列 judge 准确率 | scorer `msg` 字段（修复后可生成） |
| Markdown 解析率 | `response_df is None` 推导 |
| terminal_status / failure_stage | 真实 |
| 耗时 duration | **修复后真实**（stage 窗口；case1 从 1393s→250s） |
| 各 stage 耗时（plan/search/write）| journal `task.stage_start/end` 时间戳 |
| A1 tool 调用 / evidence | **修复后真实**（live 验证：A1 出真实 Markdown 表格） |
| A2 tool 调用/evidence | gpt-5.6-luna 下 33-85 次 tool.called、21-44 条 evidence/case |
| A2 coverage / SOCM | 四态分布（filled/unknown/conflict/empty）|
| A2-A1 配对 delta | 修复后全量 smoke 重跑中（预计 delta 非 0）|
| DRB II 三维度 + total | **live 验证完成**（rubric judge 全量/采样均出分；A1 全量 0.26）|

### ⚠️ 能测但当前 0 / 受限

| 指标 | 原因 |
|---|---|
| tokens / cost | 网关不回报 usage（deepseek 与 gpt-5.6-luna 均验证为 0） |
| fallback_count | 真实 0（无 fallback 链配置） |
| A2 coverage 填充率 | 基线 0-20%（实体建模 + 调度顺序问题，① 修复后待验证） |

### ❌ 不能测

| 指标 | 缺什么 |
|---|---|
| 首包失败 / resume/abort | 无 fallback 链 → 首包探测不生效 |
| Windows 全量离线 | P3.3 sandbox 是 Linux/macOS-only（平台性）|

## 4. 基线 smoke（修复前，gpt-5.6-luna）关键发现

**A2 每 case 真实耗时 ~250-320s**（plan 40s + search 120-135s + write 75-144s）——wall-clock 截止生效；之前 metrics 的 855s 是 collector 统计 bug。

**A2 coverage 基线（旧代码）**：

| case | filled/total | ratio |
|---|---|---|
| ws_en_002 | 6/42 | 0.14 |
| ws_en_004 | 0/42 | 0.00 |
| ws_en_007 | 5/55 | 0.20 |
| ws_en_008 | 6/36 | 0.17 |
| ws_en_011 | 2/70 | 0.07 |

**A1 全 0 的根因**：A1 用 catalog 硬编码 baseUrl（api.openai.com）→ 网关 key 401 → 首个 LLM 调用即 error → 空报告。live 验证修复后 A1 出真实表格。

**WideSearch F1 全 0 的根因**：**scorer 的 llm_judge 从未工作过**——config 拼出 `/v1/v1` + AzureOpenAI 客户端 → 404 → 每个 case `msg: evaluator error`。这就是此前"F1 太低/判罚太严"的真相（不是判罚，是 judge 挂了）。

**coverage 填充低根因**（session `01a0109a`，ws_en_004）：
- plan 把 target 名（"Samsung Galaxy US models"）当实体行 → 聚合行；14 格全 CONFLICT（40 个型号的值塞一格）
- 120s wall 内只搜了聚合行（cell-count 排序优先），两个 series 实体 28 格从未 dispatch
- 44 条 evidence 全部通过提取闸门（对 gpt-5.6-luna 提取不严格）——瓶颈在实体建模 + 调度

### 4.1 DRB II live 验证（drb2_22，换 anysearch key 后）

| 项 | 结果 |
|---|---|
| 模型网关 `pro3.o0n0o.cc` | 恢复（换 key 后通）|
| anysearch 新 key | ✅ 出 evidence（A2 单 case 9-31 条 evidence，103 tool calls）|
| tavily | ⚠️ WSL 网络不可达（HTTP 000，非 key 问题；anysearch 兜底）|
| **A2 write 结构跟随** | ✅ 修复后报告含 `## Cost Data Compilation...` 真实表格 + `## Summary of Incentive Policies...` + `## Comprehensive Analysis`；presentation 采样 0→0.667 |
| **A1 全量 judge**（45+13+7=65 条）| info_recall 0.0 / analysis **0.77** / presentation 0.0 / **total 0.256** |

**A1 画像**：能分析（模型知识，analysis 0.77 高）+ 不能召回（不搜索 → 具体事实全缺）+ 不按规范呈现（结构条目全挂）。

### 4.2 DRB II 官方参考分（arXiv:2601.08536，Gemini judge，132 题全量）

| 系统 | Info Recall | Analysis | Presentation | Total |
|---|---|---|---|---|
| GPT-o3 Deep Research | 39.98 | 49.85 | 89.16 | **45.40** |
| Gemini-3-Pro DR | 39.09 | 48.94 | **91.85** | 44.60 |
| Gemini-2.5-Pro DR | 34.91 | **51.91** | 90.24 | 41.98 |
| Doubao DR | 34.83 | 49.43 | 83.51 | 40.99 |
| Qwen3-Max DR | 34.18 | 48.04 | 74.59 | 39.25 |
| Grok Deep Search | 33.52 | 42.50 | 91.42 | 39.23 |
| Perplexity Research | 33.05 | 44.47 | 79.34 | 38.58 |
| Tongyi DR | 22.95 | 35.89 | 86.13 | 29.89 |

**规律**：连最强模型也过不了 50% rubric；Info Recall 最难（~40% 最佳）；Presentation 最容易（~90%）但和内容浅脱钩。我们分数不可直接比（单题 + gpt-5.6-luna judge），但形态一致：**recall 是最大短板，analysis 靠模型知识可到中上**。

## 5. 如何运行

```bash
# WSL（真实环境）——A2 必须用绝对路径 PYTHONPATH（相对路径在 bwrap 内解析不到）
export PYTHONPATH=/root/pi4competitive/competitive_app/src:/root/pi4competitive/packages/agent/src:/root/pi4competitive/packages/ai/src:/root/pi4competitive/eval/src
set -a; . ./.env; set +a

# A2 服务（:8000）
uv run python -m scripts.serve_app --port 8000 --no-reload
# A1 服务（:8001）
uv run python -m eval.runner.single_agent_app --port 8001

# 全量 smoke（A1+A2，5 case，~35 分钟）
uv run python -c "
import asyncio
from eval.orchestrator import run_smoke
asyncio.run(run_smoke(manifest_path='eval/manifests/widesearch_smoke.jsonl', variants=['a1','a2'],
    app_url='http://127.0.0.1:8000', a1_url='http://127.0.0.1:8001',
    budget={'max_queries': 20, 'max_fetches': 40, 'max_wall_seconds': 120}))
"

# DRB II smoke（报告轨；DRB2_MAX_ITEMS=3 采样限速, 0/缺省 = 全量 judge）
DRB2_MAX_ITEMS=3 uv run python -m eval --stage smoke --benchmark drb2 --variants a1,a2 \
  --manifest eval/manifests/drb2_smoke_1.jsonl

# 产物
#   data/evaluations/<run_id>/scores/operations.jsonl  运行指标（每 case）
#   data/evaluations/<run_id>/scores/paired_deltas.json  A2-A1 delta
#   data/evaluations/<run_id>/summary/metrics.json     汇总
#   data/evaluations/<run_id>/scores/widesearch_raw/    scorer 每 case eval_result.json
#   data/evaluations/<run_id>/scores/drb2.jsonl         DRB II 三维度 + total（报告轨）
#   data/evaluations/<run_id>/normalized/drb2_reports/  DRB II 归一化报告 .md
```

**注意**：
- `.env` 永不提交（gitignored）
- run_id 含 commit SHA——同一 commit 重跑会覆盖同名目录，重跑前 `rm -rf data/evaluations/<run_id>`
- `vendor/widesearch` 是官方 scorer，已按基准需要打补丁（config /v1 + 普通 OpenAI 客户端）——**F1 依赖它工作**
- WSL 克隆与 Windows 检出是两个独立工作树——改动需手动同步（`cp /mnt/d/python/pi4competitive/<path> <path>`）

## 6. 剩余工作

| 项 | 阻碍 | 影响 |
|---|---|---|
| WideSearch 全量 F1 重跑 | 5 case smoke 出真实 F1 + delta（scorer judge 已修） | 基准 §8 合成指数需要 |
| coverage 填充率提升验证 | 4 个修复（①）已实现 | 重跑对比基线（0-20%）是否提升 |
| DRB II 5-case 全量 + 全 judge | 单 case 全量 judge ~7 分钟；5 case 报告生成 ~35 分钟 | 稳健的 DRB II 分数 + A1/A2 delta |
| tavily 网络不可达 | WSL→api.tavily.com 连接失败（非 key）| A2 搜索仅靠 anysearch 兜底 |
| tokens/cost | 网关不回报 usage | 指标恒 0（供应商限制） |
| A2 journal 污染根因 | `journal_bridge` 闭包捕获 journal | 仅影响 duration（已规避）；可后续修 |
| DRB II rubric 判定质量 | judge 模型是 gpt-5.6-luna（官方用 Gemini）| A1 analysis 0.77 偏高可疑，需抽样复核或换官方 judge |
| info_recall 召回深度 | A2 搜索对 rubric 要求的具体数据源（如 EV 100/200/300 + Hao et al.）覆盖不足 | 报告轨 recall 维度低 |
| WSL 全量离线 10 个失败 | 6 个 P3.3 sandbox 单测 + 4 个环境依赖 | CI 门不绿（真实环境） |
