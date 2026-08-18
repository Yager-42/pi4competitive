# Eval Harness 运行指标修复进展

| 字段 | 值 |
|------|-----|
| **updated** | 2026-08-19 |
| **branch** | `p4/eval-harness-widesearch-smoke` |
| **commits** | `dfd00f7`/`ebf6637`/`d6fa1df`（指标端到端）→ `fbb7cd4`（9 指标/coverage 修复）→ `6ef385e`/`3e3c8a3`（DRB II pipeline + smoke fixes）→ `5ad7afd`（write 结构跟随）→ `7d2c833`（judge 超时 + 文档）→ `32e5a05`/`9023eeb`（plan 聚合 schema 护栏 v0.2.11）→ `685a209`/`6ad4494`（info_recall 修复 + 定性）→ `5f591bc`（A2 超时 900→1620s）|
| **范围** | 基准文档 §7 运行指标 + A1/A2 双 variant + coverage 填充质量 + DRB II 报告轨 |
| **状态** | **5-case 全量 run 完成**（全 judge，~2.7h）：A2 mean total **0.361 > A1 0.245**，实现增益 **+0.117**，A2 胜 4/5 case、三维度全面领先。recall 4/5 非零（A2 0.141 vs A1 0.088）。A2 报告 5/5 有效（drb2_4 A1 空报告 flaky）。A2 超时修复（900→1620s）是跑通关键 |

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

### 2.5 DRB II judge 单条调用超时（`7d2c833`）

full judge 实测：单条 judge 调用无超时，网关偶发挂起会阻塞整个打分（7 分钟卡死）。`evaluator/drb2.py` 加 `_JUDGE_CALL_TIMEOUT_S = 60.0`（`asyncio.wait_for`，失败按未提及计）。已 commit。

### 2.6 plan 聚合 schema 护栏（`32e5a05` + `9023eeb`，v0.2.11）

**根因**（A2 全量 judge 定位）：plan LLM 无视"实体粒度"引导，把整课题+品类当 entity（**聚合行**），brief 枚举的 12 国政策塞进一个 `Country` 格 → 搜不到 → write 无米下锅，**每节重复同一张成本表**（A2 analysis 0.077 vs A1 0.846）。

**修复**（确定性护栏，不依赖 LLM 自觉）：

| 组件 | 说明 |
|---|---|
| `domain/socm/coverage.py` | `CoverageMap.from_schema` 新增可选 `entity_attributes` 每实体属性作用域（缺省 = 原笛卡尔积，向后兼容）|
| `plan_normalize.py`（新）| 提取 brief 枚举项（"cover at least / such as / including / the following ..."）→ 逐项建 entity → **政策属性作用域给 item 实体、成本属性留给原实体** → 补定向查询 |
| `research_runner.py` | plan 阶段 apply 护栏 |
| 测试 | 10 个新单测（含真实 brief 回归）|

**提取误报修正**（`9023eeb`，用真实 drb2_22 brief 全量验证）：`columns including:` 列名规格 / `the following sections` 章节名 / DRB II blocked-reference JSON 块（`{`/`[` 截断）/ `"Canada and Spain"` 的 and 连接——全部不作行实体。最终精确提取 12 国。

**Live 验证**（drb2_22，全量 65 条 judge）：

| 维度 | 旧 A2（聚合行） | **新 A2（护栏）** | A1 |
|---|---|---|---|
| info_recall | 0.000 | 0.000 | 0.000 |
| analysis | 0.077 | **0.769** | 0.846 |
| presentation | 0.429 | **0.857** | 0.143 |
| **total** | **0.168** | **0.542** | 0.330 |

**A2 反超 A1（0.542 > 0.330），实现增益 +0.21**。新报告政策节是**真实 12 国表**（Policy Name/Year/Brief + 真实来源引用 tc.canada.ca / afdc.energy.gov / IEA / EU observatory… + Switzerland 诚实标"未找到可靠来源"），对比旧报告的重复成本表。A2 operations 真实：105 search / 161 fetch / 266 tool calls / 549 evidence / 831s。

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
| tokens | **已可测**（v0.2.11 重跑：gpt-5.6-luna 回报 usage，A2 run 5.47M tokens）|
| cost | 恒 0（provider usage.cost 返回 0 价）|
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
| **A1 全量 judge**（45+13+7=65 条）| info_recall 0.0 / analysis **0.77** / presentation 0.0 / **total 0.256**（重跑 0.33，judge 抖动 ±0.07）|
| **A2 全量 judge + plan 护栏**（`32e5a05`）| info_recall 0.0 / analysis **0.769** / presentation **0.857** / **total 0.542**；政策节真实 12 国表；A2 反超 A1（+0.21）|
| **A2 + info_recall 修复**（`685a209`）| info_recall **0.0**（仍 0）/ analysis 0.769 / presentation **1.0** / **total 0.590**；成本表研究索引化（FSEC + Sheth 两来源分行、诚实省略无数值研究）|
| **tokens** | gpt-5.6-luna 回报 usage → 可测（A2 run 5.47M）；cost 仍 0 |

**A1 画像**：能分析（模型知识，analysis 0.77 高）+ 不能召回（不搜索 → 具体事实全缺）+ 不按规范呈现（结构条目全挂）。
**A2 画像（护栏后）**：能分析（0.77，含政策综合）+ 能呈现（1.0，结构+表格精确）+ 仍不能召回（0.0，成本节只有单来源、缺 rubric 指定的具体研究数据）。

**info_recall 0.0 定性（`685a209` 后，judge 探测坐实）**：judge 公平——报告确实有 "Nissan Leaf + FSEC" 时判 1，报告只有 "Sheth bus" 而 rubric 要 "SOR-NS-12" 时判 0（reason 明确"未识别具体型号/来源"）。**0.0 是真实测量：报告 0/45 条精确条目未满足**。根因是搜索检索不到 DRB II 参考语料（Hao et al. EV 300=$1,994,243、SOR、Edison project 等具体研究/政策），不是 judge 过严。换 Gemini judge 不会改变结论。structural 修复（研究索引表）已让 presentation 满分、total 0.590。

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

### 4.3 5-case 全量 run（全 judge，`smoke-drb2-1962711-f896509`）

**前置修复**（`5f591bc`）：A2 per-task 超时守卫 **900s→`max_wall+900`（720→1620s）**——原 900s 硬编码下，A2 大 schema 的 search（720s wall）+ plan + write 超时被 harness POST `/abort` → 空报告（drb2_4 A2 曾因此死）。此修复是 5-case 跑通的关键。

**完整结果**（gpt-5.6-luna judge，132→各 case 全量 rubric）：

| case | A1 total | A2 total | delta | 主题 |
|---|---|---|---|---|
| drb2_6 | 0.225 | 0.433 | **+0.208** | |
| drb2_22 | 0.359 | 0.542 | **+0.183** | EV LCC |
| drb2_4 | 0.000（空报告）| 0.140 | +0.140 | |
| drb2_30 | 0.192 | 0.258 | +0.066 | |
| drb2_18 | 0.447 | 0.434 | −0.013 | 植物 HGT |

**维度均值**：

| 维度 | A1 | A2 | A2 增益 |
|---|---|---|---|
| info_recall | 0.088 | **0.141** | +0.053 |
| analysis | 0.283 | **0.396** | +0.113 |
| presentation | 0.364 | **0.548** | +0.184 |
| **total** | **0.245** | **0.361** | **+0.117** |

**结论**：
- **A2 胜 4/5 case，实现增益 +0.117**——完整链路（plan 护栏 + 结构跟随 + 研究索引 + 超时修复）确实优于裸 agent 基线，三维度全面领先
- **recall 4/5 非零**（仅 drb2_22=0）——搜索采到部分具体条目，但精确数值（EV 300=$1,994,243）仍采不到（见 §6）
- **analysis 分化**：泛化题 drb2_22=0.77、科研题 drb2_18/4=0.18——具体文献依赖型分析 = recall 同款检索短板
- **A1 flaky**：drb2_4 A1 空报告（"(no output)"，研究型 brief 时模型工具调用落地失败）；需"空输出重试"
- 期间 2 次网关额度故障（报告生成 + judge 全 0）→ 用户充值后重跑；此 run 无故障

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
| coverage 填充率验证 | **护栏后大幅提升**（drb2_22 policy 格 0→真实 12 国）；WideSearch 侧待重跑 | 对比基线（0-20%）是否提升 |
| ~~DRB II 5-case 全量 + 配对 delta~~ | **✅ 完成**（`4.3`，A2 mean 0.361 > A1 0.245，+0.117）| 基线结果已入库 |
| **A1 空输出 flaky** | drb2_4 A1 产 "(no output)"（研究型 brief 时模型工具调用落地失败）；加"空输出自动重试"或换可靠 provider | A1 基线质量；空报告拉低均值 |
| **drb2_30 A2 presentation 0.200** | 结构未跟随（该 case 报告结构有 4 节但可能标题/表不匹配）| 特定 case 的 write 结构问题，需单独看 |
| tavily 网络不可达 | WSL→api.tavily.com 连接失败（非 key）| A2 搜索仅靠 anysearch 兜底 |
| cost | provider usage.cost 返回 0 价 | 成本指标恒 0（供应商限制）；**tokens 已可测** |
| A2 journal 污染根因 | `journal_bridge` 闭包捕获 journal | 仅影响 duration（已规避）；可后续修 |
| DRB II rubric 判定质量 | judge 模型是 gpt-5.6-luna（官方用 Gemini）| A1 analysis 0.77 偏高可疑，需抽样复核或换官方 judge |
| **info_recall（search-capability 天花板）** | `685a209` 结构已修（研究索引 + 车型展开 + 逐研究提取）；**搜索仍采不到 rubric 精确语料**（EV 300=$1,994,243、SOR bus、Edison project…）；5-case 中 4/5 recall 非零（A2 0.141），仅 drb2_22=0 | GPT-o3 也仅 ~40%。提升需学术搜索源（Scholar/Semantic Scholar）+ 逐国/逐研究更深检索 |
| WSL 全量离线 10 个失败 | 6 个 P3.3 sandbox 单测 + 4 个环境依赖 | CI 门不绿（真实环境） |
