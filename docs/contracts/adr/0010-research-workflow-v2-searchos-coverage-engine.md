# ADR 0010: P4 research-workflow v0.2.0 — SearchOS coverage 引擎复现

- **status:** accepted
- **date:** 2026-07-28
- **contract_version_before:** 0.3.5
- **contract_version_after:** 0.3.6
- **supersedes (局部):** `research-workflow-v1` 的 **F-R2 / F-R3 / F-R7 / F-R10**（仅此 4 项；其余 locked 决策不变）
- **does not supersede:** ADR 0007（旧仓身份）、ADR 0008（extension runtime 边界）、约束 3（禁第二 LLM 框架）、D24/D25（JSONL 对话 SoT）、F-R14/F-R16/F-R17/F-R18/F-R21/F-R13
- **feature contract:** [`docs/features/research_workflow_v1.md`](../../features/research_workflow_v1.md) **frozen v0.2.0**
- **drives:** `competitive-app-http-v1` → **v0.3.0**（投影 `stages` 6→3 + `coverage` 子字段）

## Context

`research-workflow-v1` v0.1.1（frozen 2026-07-26）的六阶段线性流水线（plan→collect→analyze→write→review→cite）已 L1 live 验证（DeepSeek + tavily/anysearch/grok 真搜索，六阶段全 ok，报告非空）。但它在搜索质量上有结构性局限：

1. **evidence 散在对话**：collect 的证据只存在 messages 里，无共享状态；analyze 要从对话里捞，易丢、易不一致。
2. **单 agent 串行搜**（F-R2 locked 砍了 fan-out）：一次只发一个 query，recall 不足，长尾实体搜不到。
3. **无 gap 补搜**（F-R3 locked 砍了回退/补搜）：analyze 产 gaps 但不触发回 collect，缺口永远缺。
4. **无 citation 锚定**：cite 阶段是事后从对话反推 claim→source，弱于"每个事实自带来源"。

[`antins-labs/SearchOS`](https://github.com/antins-labs/SearchOS)（arXiv 2607.15257）用机制级方案解了这四点：**coverage-map 驱动 + SOCM 共享状态 + 并行 sub-agent + judge 自动抽取**。其评测在 WideSearch/GISA 上 recall 大幅领先（Set·F1 +13.4 over 次优基线），增益主要来自"一直填空 cell 直到每个都有带来源的值"。

但 SearchOS 全栈跑在 `langgraph + langchain + langchain-anthropic + deepagents` 上（~14 万行），与本仓**约束 3**（`tests/packages/*/contract/test_deps.py` AST 扫描禁 langchain/langgraph/llama_index 等）和**约束 2**（唯一 agent 内核 = `packages/agent`）硬冲突。字面搬运不可行，且 SearchOS 的 skills 系统（248 access skill）、TUI、多表+外键、steering 对"竞争分析"这个限定域是过度设计。

**决策方向**：复现 SearchOS 的**架构骨架**（SOCM + coverage 派发 + Extraction + Sensor），用本仓 `pi_agent`/`pi_ai` 栈重写，不引其框架依赖；砍掉限定域不需要的组件。同时把六阶段砍成三阶段（plan/search/write），让 coverage 引擎有迭代空间（线性六阶段的"跑一遍就过"和"填表到满"语义冲突）。

## Decision

### D-S1 — 规范源与 SearchOS 参考身份

| 项 | 值 |
|----|-----|
| 产品/仓库名 | **SearchOS**（`antins-labs/SearchOS`） |
| 远程 | https://github.com/antins-labs/SearchOS |
| 本地约定 | 与本仓 `pi4competitive` **并排检出** 的 `SearchOS/` |
| 角色 | **`research-workflow-v1` v0.2.0 引擎架构参考**（coverage map / SOCM / Extraction / Sensor 概念来源） |
| 约束 | **非**代码父本；**非** 1:1 复刻 backlog；**禁止**引入 langgraph/langchain/deepagents（约束 3 仍管） |

SearchOS 地位弱于 ADR 0007 的旧仓：旧仓是"业务形状参考"，SearchOS 是"引擎架构参考"。复现的是**概念**（coverage 派发、evidence graph、judge 抽取、loop 检测），**不是代码同构**——TS→Python 同构对象仍仅为 `earendil-works/pi` main（D2/D14）。SearchOS 的 langgraph StateGraph / MemorySaver / `@tool` / AgentMiddleware 等机械件，用本仓 `AgentHarness`/`agent_loop`/`AgentTool`/`extensions` runtime 对应替换（见 §"langgraph 映射"附录）。

### D-S2 — 三阶段替换六阶段（supersedes F-R10 局部）

`STAGES = (plan, search, write)`，替换 v0.1.1 的 `(plan, collect, analyze, write, review, cite)`。

| 阶段 | 职责 | 对应 SearchOS |
|------|------|---------------|
| `plan` | Explore 侦察 + 建 coverage map（据 brief 的 target+competitors+dimensions 产出搜索计划 + 实体×属性表） | Explore + Schema |
| `search` | 迭代核心：派发空 cell → 并行 sub-agent 搜 → judge 抽 evidence 进图 → 评估空 cell → 补搜，直到终止 | Dispatch + Extract + Assess（循环） |
| `write` | 从 SOCM 合成带 citation 的报告 | Synthesize |

`analyze` 与 `cite` 的**职责保留但不作为独立 stage**：冲突仲裁→Extraction/coverage 填充时实时进 evidence graph 的 support-conflict 边；空 cell 定位→`search` 循环评估步；citation→evidence node 自带 source，`write` 直接拼。

### D-S3 — coverage_schema（plan 产物）

单表（v0.2.0 不做多表+外键，砍 SearchOS 的 multi-table）。`plan` 产物带 `coverage_schema`：

```jsonc
{
  "plan": "搜索计划文本",
  "coverage_schema": {
    "table_id": "t_competitive",
    "entities": [{"id": "e_notion", "name": "Notion", "kind": "target|competitor"}],
    "attributes": [
      {"id": "a_pricing_free", "name": "免费层", "dimension": "pricing",
       "type": "text|money_usd|bool|number|enum:<values>", "validation": "non_empty|currency_or_unknown|yes_no"}
    ]
  }
}
```

- **维度→属性由 LLM 展开**（plan 阶段唯一智能工作），带 fallback（dimensions 直接当列）+ 校验（≥1 实体×≥1 属性，attribute id 唯一，dimension 必来自 brief）。
- **属性 type 封闭枚举**：`text / money_usd / bool / number / enum:<values>`（5 种）。Extraction 按 type 归一化，`write` 按 type 格式化。
- **cell 四态**：`empty`（未搜）/ `filled`（有值，带 value+source+source_excerpt+confidence）/ `unknown`（搜了找不到，带 attempts）/ `conflict`（多源冲突，带 candidates）。`unknown` 让 search 知道"派发过但无果，别重派"，是终止条件的关键。
- **冲突仲裁规则**（`fill()` 语义）：新 evidence 进 cell 时——
  - cell 当前 `empty` → 直填 `filled`（value/source/confidence 来自该 evidence）。
  - cell 当前 `filled`，新值与现值**相同**（归一化后）→ `support`，confidence 取高者，状态留 `filled`。
  - 新值与现值**不同**：confidence 差 ≥ `CONFLICT_CONFIDENCE_DELTA`（默认 0.2）→ 高 confidence 胜出填 `filled`，低者进 evidence graph 的 `conflict` 边（可追溯）；confidence 差 < 阈值 → 状态转 `conflict`，`candidates` 保留双方（`write` 阶段标注多源）。
  - cell 当前 `conflict` → 新值加入 `candidates`，重算仲裁。

### D-S4 — SOCM = 搜索 SoT（澄清 D24）

SOCM（Frontier 任务队列 + Evidence Graph + Coverage Map + Strategy Memory）是**搜索状态的唯一真相源**，落盘 `data/sessions/<session_id>/search_state.json`。

- **原子写**：read-modify-write + `os.replace`（SearchOS `workspace.py:atomic_update_state` 模式），per-table `asyncio.Lock` 串行化 flush（v0.2.0 单表 = 一把锁）。
- **SQLite `projection_json.coverage` 是 SOCM 的只读投影**（periodic snapshot），非独立数据源——与 D24「JSONL 是对话 SoT，SQLite 是投影」完全对称：JSONL=对话 SoT，SOCM=搜索 SoT，SQLite=两者投影。
- **D24 不变**：D24 管"对话/tool SoT"，evidence 是搜索状态非对话；SOCM 落盘即合规（D24 反面是"仅内存当默认 SoT"）。

### D-S5 — sub-agent ephemeral

sub-agent（search 阶段的并行 ReAct worker）**不持久化**：其 findings 通过 Extraction 写进 SOCM（已落盘），其 ReAct 对话是过程产物，任务结束即丢。

- sub-agent 是"工具调用序列"，不是"会话"——与"agent loop 内部 tool 中间步骤不单独存"同理。
- `GET /tasks/{id}/sessions` 的 1:1 假设不变（F-R14 保留）：sub-agent 不另建 JSONL session。
- 可追溯性靠 evidence node 的 `source_excerpt` + `page_id`，不靠 sub-agent 对话回放。

### D-S6 — judge 独立模型（supersedes F-R7 局部）

Extraction 的 judge LLM（从页面抽 entity/attribute/value/source/confidence）用独立模型，env `JUDGE_MODEL` 配置，**默认 fallback 到主模型**（不配时退化成 v0.1.1 的单模型行为，不增必填配置）。

- **局部反转 F-R7**：仅对 judge 放开多模型（judge 是无状态抽取器，非对话 agent，故豁免 F-R7）；orchestrator/sub-agent/write 仍单模型。
- judge 不走 `AgentHarness`，是裸 `models.streamSimple(model=judge_model, ...)` 调用（单次"给文本要 JSON"，不需 agent loop）。
- judge **批量调**：一次一个实体的所有空 cell（不是一次一个 cell），降调用数。
- **`JUDGE_MODEL` 解析**：env 字符串经 `_ModelResolver.resolve(judge_model_id)` 复用现有 catalog/gateway 解析路径（`wiring.py` 的 `_ModelResolver`）→ 得 pi_ai Model dict；解析失败或未配 → fallback 主模型（`config.default_model`）。wiring 暴露 `judge_model: dict` 给 `EvidenceIntake`。

### D-S7 — Extraction 挂 extension `tool_result` + ContextVar

Extraction 作为 extension 挂 `tool_result` 事件（`extensions/types.py` 已有该事件；`runner.emit_tool_result`）：

- 过滤 `toolName in {*_fetch}`（事件字段为 camelCase `toolName`，沿用上游 TS 语义，`agent.py:494` emit；非 `tool_name`），从 `tool_result` 的 result details 取页面全文。
- 从**当前 sub-agent 的 ContextVar** 取抽取目标（实体 + 空 cell 列表）——由 `coverage_engine` 在 spawn sub-agent 时 `copy_context` 注入（对应 SearchOS `set_current_table` / `_current_task_var`）。
- 异步进 EvidenceIntake（buffer + batch flush，不阻塞 agent loop）。**sub-agent 退出时强制 flush**（drain point），防止 buffer 内 evidence 丢失。

不覆盖 fetch 工具本身（capability 包应只做 fetch，不该知道 SOCM/judge）。

**judge 输入**：judge 接收该 sub-agent 为当前实体收集的所有 `*_fetch` 页面全文（按 `page_id` 标记拼接）；若总量超 `JUDGE_MAX_INPUT_TOKENS`（默认 50000）截断保留末尾。judge prompt 模板见 plan §5 D2。

**judge 失败处理**：judge 返回非法 JSON 或异常 → 该实体本轮空 cell 不填（保持 `empty`），释放 content_hash 允许下一轮重试（最多 `JUDGE_MAX_ATTEMPTS=2`，对应 SearchOS `_settle_content_hashes` 两阶段提交）；连续失败 → cell 标 `unknown`（attempt+1），不阻塞终止。

### D-S8 — search 终止三层 OR（supersedes F-R2 / F-R3 局部）

`search` 阶段外层编排循环，**任一**条件满足即终止进 `write`：

| 层 | 条件 | 作用 |
|----|------|------|
| 1. 覆盖率达标 | `filled / total ≥ SEARCH_COVERAGE_THRESHOLD`（默认 0.8） | 正常出口；不要求 1.0，允许 unknown 进 write |
| 2. 预算耗尽 | 5 维消耗预算任一触底：`SEARCH_MAX_QUERIES` / `SEARCH_MAX_FETCHES` / `SEARCH_MAX_ITERATIONS` / `SEARCH_MAX_WALL_SECONDS` / `SEARCH_MAX_OPENS` | 兜底防无限搜 |
| 3. 无进展 | 连续 `SEARCH_MAX_STALLED_ITERATIONS`（默认 3）轮派发但 filled 数未增（Sensor 判定） | 防卡死 |

- **并行上限**（非预算，是并发 cap）：`SEARCH_MAX_PARALLEL=4`（asyncio Task 池 + `FIRST_COMPLETED` 回收）。`SEARCH_MAX_PARALLEL` 不被"消耗"，只限 in-flight 数，故**不计入 5 维预算**。
- **F-R2 反转**：collect 串行 → search 并行 fan-out。
- **F-R3 反转（局部）**：search **阶段内**循环补搜（空 cell 重派）；但 **stage 间仍不回退**（write 不回 search）。stage 内 retry 仍由 Sensor 管，非自动重试。
- env 细粒度配置，**不引 effort 档位**（砍 SearchOS 的 low/medium/high/max，v0.2.0 后续可加）。

### D-S9 — 砍（v0.2.0 不做）

| 砍 | 理由 |
|----|------|
| Skills 系统（248 access + 40 strategy） | 竞争分析查公开页，judge extraction + tavily_fetch 够用；省 ~80% 代码 |
| TUI（Textual） | 本仓走 FastAPI，不需 TUI |
| 多表 + 外键 coverage | 竞争分析单表（行=公司，列=维度）足够；开放域才需多表 |
| mid-run steering | 体验加分项，非搜索能力核心，延后 |
| effort 档位 | env 细粒度先行，档位后续 |

## Patch v0.2.1 — 搜索质量第一步修复（局部反转 D-S3 / D-S6 / D-S8 的"一轮单源"默认）

- **status:** accepted
- **date:** 2026-07-29
- **supersedes (局部):** D-S3 cell 四态语义、D-S6 judge prompt、D-S8 终止条件 1 的"覆盖率"口径
- **does not supersede:** D-S1/D-S2/D-S4/D-S5/D-S7/D-S9、约束 2/3、D24/D25、F-R14/F-R16
- **feature contract:** [`docs/features/research_workflow_v1.md`](../../features/research_workflow_v1.md) **v0.2.1**

### 背景：v0.2.0 的"一轮单源"短路

v0.2.0 落地后实测（2026-07-29 三阶段 vs 六阶段对比实验，题：小米17 vs iPhone17 中国大陆）暴露一条因果链：judge 对搜不到的 cell 塞占位值（`"Not specified"` / `"N/A"` / `"未知"`）→ cell 全转 `filled`（`unknown` 状态因 `mark_unknown` 未被调用而**不可达**）→ `empty_cells()` 返回空 → search loop 一轮即 `break`（`coverage_ratio()` 把 junk `filled` 也算 covered，ratio→1.0 ≥ 0.8）→ 每 cell 恰好 1 源 → `fill()` 的 candidates 仲裁路径不触发 → evidence graph 边是死结构。

结果：三阶段被短路成"一轮 × 单源/cell × 填满即停"，在需要多权威源的硬件题上输给六阶段自由 collect（4 泛源 vs 六阶段 16 源）。这不是架构不行，是架构被饿死。

### D-S3'（patch）— cell 四态语义修正

`unknown` 状态在 v0.2.0 不可达（`mark_unknown` 零调用）；v0.2.1 接通：

- **junk 占位过滤**：Extraction `_fill` 回调对 judge 返回的 value 做 `_is_junk_value` 判定（中英占位模式：`Not specified` / `N/A` / `未知` / `未公布` / `暂未公布` / `TBD` / `—` 等，归一化后精确匹配）。命中 → `coverage_map.mark_unknown(entity, attr)`（`attempts++`），**不 fill**。
- **低置信过滤**：`confidence < SEARCH_MIN_CONFIDENCE`（默认 0.4）的 finding 同样走 `mark_unknown`，不 fill。
- **actionable 谓词**：新增 `CoverageMap.actionable_cells(max_attempts)` = EMPTY ∪ UNKNOWN[attempts<N] ∪ FILLED[confidence<WEAK_CONFIDENCE 且 0<attempts<N]。CONFLICT 终态。N = `SEARCH_MAX_CELL_ATTEMPTS`（默认 2）。
- **satisfied 谓词**：新增 `CoverageMap.satisfied_ratio(max_attempts)` = (强 filled[conf≥WEAK_CONFIDENCE] + conflict + 放弃 terminal[unknown/弱filled 且 attempts≥N]) / total。`WEAK_CONFIDENCE` 默认 0.7。
- **D-S3 原文不变**：四态定义、`fill()` 仲裁规则、`CONFLICT_CONFIDENCE_DELTA=0.2` 均保留；仅接通 `unknown` + 加 actionable/satisfied 谓词。

### D-S6'（patch）— judge prompt 强约束 + 多源抽取

v0.2.0 judge prompt 允许占位值且每 attr 只抽 1 条；v0.2.1 收紧：

- **禁占位**：prompt 显式 "Never return placeholder values ('Not specified'/'N/A'/'未知'/'未公布'/...); if a page does not state the value, OMIT that attribute."
- **多源抽取**：prompt 改为 "one object PER (attribute, source) pair"——同一 attr 若多页面支撑，返回多条，触发 `fill()` 的 support/conflict 仲裁（candidates 路径终于可达）。
- **置信度分级**：prompt 给 confidence 量级锚（官方 spec=0.9 / 权威评测=0.7 / 论坛聚合=0.4），配合 D-S3' 低置信过滤。
- **D-S6 原文不变**：judge 独立模型、`JUDGE_MODEL` fallback、批量调（每实体一次）、裸 `completeSimple` 调用方式均保留。

### D-S8'（patch）— 终止条件 1 口径修正

v0.2.0 终止条件 1 用 `coverage_ratio()`（非 EMPTY 即算 covered，含 junk filled）→ 一轮早退；v0.2.1 改用 `satisfied_ratio()`：

| 层 | v0.2.0 | v0.2.1 |
|----|--------|--------|
| 1. 覆盖率达标 | `coverage_ratio() ≥ 0.8`（junk filled 算 covered） | `satisfied_ratio() ≥ 0.8`（只算强 filled + conflict + 放弃 terminal） |
| 2. 预算耗尽 | 不变 | 不变 |
| 3. 无进展 | `filled_count` 不增 | `satisfied_ratio` 不增（口径对齐） |

dispatch 对象从 `empty_cells()` 改为 `actionable_cells()`——弱值/junk 的 cell 被重派，第 2 个 candidate 进来触发仲裁。

### D-S2a / D-S2b（新增）— query 策略 + subtask 拆细

v0.2.0 sub-agent 拿裸 "填这些 cell" 泛 query，命中 aggregator 弱源；v0.2.1 补：

- **D-S2a 结构化 queries**：plan 产物新增可选 `queries` 字段（`[{entity_id, queries[], source_hints[]}]`），plan prompt 要求每实体 3-5 个类型化 query（官方页/规格页/评测页/媒体页）+ source_hints。`coverage_engine._parse_plan_queries` 解析后注入 subtask，`_build_subagent_prompt` 把 queries + hints 喂给 sub-agent。
- **D-S2b subtask 拆细**：`_build_subtasks` 从"一实体一 subtask"改为"按 `SEARCH_SUBTASK_CHUNK`（默认 3）切分"，让并行池能填满 `max_parallel`（v0.2.0 的 2 实体 → 2 sub-agent 并发被实体数卡死）。
- **多源约束**：sub-agent prompt 显式 "for EACH target cell, fetch at least 2 independent sources from DIFFERENT domains"。

### 不做（v0.2.1 边界）

- **不上完整 Tier-1 重搜 loop 的质量模型**（弱 FILLED 主动再搜 + 完整 assess/adjust）——实验已证明第一步够用（两题三阶段搜索质量均显著优于六阶段：源权威性 87%/31% vs 47%/13%、0 junk、多源 cell 42/26）。
- **不接 evidence graph 边**（`add_edge`/`get_conflicts` 仍死代码）——多源仲裁已由 `fill()` candidates 路径承担。
- **不接 Frontier / StrategyMemory**（仍死代码）——subtask 仍用本地 list，无 assess/adjust 策略调整。
- **不引入 explore_agent**——用 plan 结构化 queries（方案 A），不上完整 scouting。
- **不改 D*/G* 核心、不改 14 路由、不改 packages/ai|agent**。

### 实验证据（2026-07-29）

| 组 | 架构 | 源 | 权威% | evidence | 多源cell | junk |
|----|------|-----|-------|----------|---------|------|
| three_t1 | 三阶段 v0.2.1 | 15 | 87% | 128 | 42 | 0 |
| six_t1 | 六阶段 | 19 | 47% | 21 | — | — |
| three_t2 | 三阶段 v0.2.1 | 29 | 31% | 113 | 26 | 0 |
| six_t2 | 六阶段 | 23 | 13% | 24 | — | — |

产物：`data/live_runs/comparison_v021/`（含 SOCM、session JSONL、对比报告）；live 验证 `data/live_runs/xiaomi17_vs_iphone17_cn_FIXED/`。



| SearchOS（langgraph 栈） | 本仓替换 |
|--------------------------|----------|
| `deepagents.create_deep_agent` ReAct 循环 | `pi_agent.AgentHarness` / `agent_loop` |
| `langchain_core.tools.@tool` | `pi_agent.AgentTool` |
| `ChatOpenAI` / `ChatAnthropic` | `pi_ai` providers + `models.streamSimple` |
| `MemorySaver` + thread_id resume | `JsonlSessionRepo`（持久 JSONL，比 MemorySaver 强） |
| `langchain AgentMiddleware`（Context/Sensor/Extraction） | `pi_agent.extensions` runtime（`tool_call`/`tool_result`/`before_provider_request` 事件） |
| langgraph `Send` 并行 fan-out | asyncio Task 池 + `FIRST_COMPLETED` |
| `astream(stream_mode="values")` | `agent_loop` 事件流 |

## Consequences

1. **搜索 recall 提升**（coverage 填表 + 并行 + judge 抽取 + 空cell补全），代价是 `search` 阶段复杂度上升（并行 sub-agent + SOCM + 三层中间件）。
2. **judge 是成本乘子**（每页每实体一次 LLM 调用）；`JUDGE_MODEL` 可配便宜模型缓解，默认 fallback 主模型不增配置。
3. **三层 SoT 并存**：JSONL（对话 SoT）+ SOCM `search_state.json`（搜索 SoT）+ SQLite（两者投影）。resume 优先读 SOCM 恢复 coverage 状态。
4. **砍 skills 意味着反爬/登录墙站点覆盖弱**——对竞争分析（公开定价/功能页）可接受；若后续需要，skills 作为独立 feature 再引。
5. **契约测试**须新增：SOCM 落盘原子性、sub-agent 不落 JSONL、judge 模型 fallback、coverage 四态、search 终止三层。**约束 3 AST 扫描已扩展**：`tests/packages/{ai,agent}/contract/test_deps.py` 的 forbidden set 加 `langgraph/langchain_anthropic/langchain_openai/deepagents`；`tests/competitive_app/contract/test_deps.py` 新增 `test_no_forbidden_llm_frameworks_in_app` 扫全 `competitive_app/src`（SearchOS 参考不得引入其依赖，day-one 可验）。
6. **v0.1.1 六阶段代码临时共存**：PR2-5 期间 v2 引擎与 v1 runner 并存为实现细节（不破契约）；PR6 删 v1 runner + 重写测试。最终终态单一 v0.2.0。

## Alternatives rejected

| 方案 | 原因 |
|------|------|
| 字面搬 SearchOS 代码 | langgraph/langchain 违约束 3；14 万行不可维护 |
| 并存 v1/v2 两套 workflow（新 feature_id） | 两套 runner/测试/投影共存是技术债；用户已否决"并存"终态 |
| 只搬 SearchOS Web 接口层（steer/WS/branching） | 拿不到搜索能力（coverage/evidence/并行），答非所问 |
| 保留六阶段只增强 collect | 线性"跑一遍就过"与"填表到满"语义冲突；analyze/cite 独立阶段在迭代模型下多余 |
| SearchOS 作规范源（TS→Python 同构） | SearchOS 跑 langgraph，同构会逼复制图结构，违约束 3 |
| SearchOS 不入契约仅口头参考 | `agents.md` §33「chat-only 架构变更无效」；既驱动 ADR 0010 须入契约标身份 |

## Implementation pointer

- Feature：[`docs/features/research_workflow_v1.md`](../../features/research_workflow_v1.md) **v0.2.0 frozen**
- Plan：`docs/plans/P4_research_workflow_v2.md`（PR2 起随实现补）
- 参考源：`SearchOS/`（并排检出；`searchos/socm/`、`searchos/harness/middleware/`、`searchos/agents/orchestrator/`）
- 分期：PR1 文档冻结（本 ADR + 三份 feature 契约 bump）→ PR2 `domain/socm/` → PR3 3 阶段 runner 骨架（单 sub-agent 串行跑通）→ PR4 并行池 + Sensor → PR5 Extraction intake → PR6 `write` + resume + live 测试 + 删 v1
