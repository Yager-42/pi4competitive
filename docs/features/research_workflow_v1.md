# Feature 边界契约：research-workflow-v1

| 字段 | 值 |
|------|-----|
| **feature_contract_version** | `0.2.3` |
| **status** | **frozen** |
| **updated** | 2026-07-30 |
| **feature_id** | `research-workflow-v1` |
| **roadmap_stage** | **P4** `competitive_app` —— 三阶段研究 workflow（SearchOS coverage 引擎复现；替换 v0.1.1 六阶段） |
| **architecture_contract** | [`ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.6**（§3.2 / D8 / G1 / G2 / D24 + ADR 0010） |
| **roadmap** | [`ROADMAP.md`](../ROADMAP.md) §2 P4 / §4 业务能力引入 |
| **plan** | [`docs/plans/P4_research_workflow_v2.md`](../plans/P4_research_workflow_v2.md)（PR2 起随实现补） |
| **path** | `docs/features/research_workflow_v1.md` |
| **参考源（引擎架构）** | [`antins-labs/SearchOS`](https://github.com/antins-labs/SearchOS) —— `research-workflow-v1` v0.2.0 引擎架构参考（coverage map / SOCM / Extraction / Sensor 概念来源；**非**代码父本，**非** 1:1 复刻；**禁** langgraph/langchain/deepagents；ADR 0010 D-S1） |
| **参考源（业务形状）** | 旧仓 [`xj120/competitive-agent`](https://github.com/xj120/competitive-agent) **`rr-refactor`** `backend/workflows/competitive/`（D12/ADR 0007；ResearchBrief 结构参考） |
| **关系** | 落地后同步升级 [`competitive-app-http-v1`](competitive_app_http_v1.md) → **v0.3.3**（三阶段投影 + evidence/clarify/dashboard/subscription HTTP 增量） |

---

## 0. 效力与状态

1. 本文是 **P4 三阶段研究 workflow** 的 **frozen** 功能边界（v0.2.0 grill 收敛于 2026-07-28，31 决策见 §8；v0.1.1 grill 收敛于 2026-07-26，24 决策）。
2. 标为 **locked** 的决定不得由实现者自行改写；变更须重新 grill 并升 `feature_contract_version`。
3. §6 验收标准为 **locked**。
4. 变更本边界 = 业务范围变更，须同步 `docs/ROADMAP.md`。
5. 本文**升架构契约**至 v0.3.6（ADR 0010）；三阶段代码落 `competitive_app/`（§3），不下沉 `packages/agent`（D8 禁止）。
6. **v0.2.0 反转 v0.1.1 的 F-R2 / F-R3 / F-R7 / F-R10**（局部，见 §8 + ADR 0010）：六阶段→三阶段、串行→并行 fan-out、单模型→judge 局部多模型、6 阶段 schema→3 阶段 schema + SOCM。其余 locked 决策不变。

---

## 1. 动机与目标（locked grill）

### 1.1 问题

v0.1.1 六阶段线性流水线（plan→collect→analyze→write→review→cite）已 L1 live 验证，但搜索质量有结构性局限：

1. **evidence 散在对话**：collect 证据只存 messages，无共享状态；analyze 从对话捞，易丢、易不一致。
2. **单 agent 串行搜**（F-R2）：一次一个 query，recall 不足，长尾实体搜不到。
3. **无 gap 补搜**（F-R3）：analyze 产 gaps 但不回 collect，缺口永远缺。
4. **无 citation 锚定**：cite 阶段事后从对话反推 claim→source，弱于"每个事实自带来源"。

SearchOS（arXiv 2607.15257）的 coverage-map 驱动 + SOCM 共享状态 + 并行 sub-agent + judge 抽取是机制级解法（WideSearch/GISA recall 大幅领先）。但其 langgraph 栈违约束 3，故复现架构骨架用本仓 `pi_agent`/`pi_ai` 重写（ADR 0010）。

### 1.2 目标（locked）

1. **三阶段** `STAGES = (plan, search, write)`，替换六阶段（D-S2 / F-R25）。
2. `plan` 产搜索计划 + coverage_schema（实体×属性表）。
3. `search` 迭代核心：派发空 cell → 并行 sub-agent 搜 → judge 抽 evidence 进 SOCM → 评估空 cell → 补搜，直到终止（D-S8 / F-R31）。
4. `write` 从 SOCM 合成带 citation 的报告（每个事实自带 source）。
5. SOCM = 搜索 SoT，落 `search_state.json`（D-S4 / F-R27）；JSONL 仍为对话 SoT（D24 不变）。
6. resume 接着跑（跳过已 ok stage + 恢复 SOCM），abort 后可 resume（F-R16/F-R17 保留）。

### 1.3 非目标（locked grill）

| 不做 | 说明 |
|------|------|
| stage 间回退（write 回 search） | 保留 v0.1.1 F-R3：stage 间严格顺序，不回退。**search 阶段内**循环补搜不算回退 |
| stage 内自动 retry | 保留 v0.1.1 F-R3：失败→failed，不自动重试（Sensor 的 loop 检测是行为约束，非 retry） |
| 多角色评审 + 投票共识 | 保留 v0.1.1 F-R11 砍：review 职责并入 write（从 SOCM 合成时自审） |
| 前置 2 接口（resolve-target / discover-competitors） | 保留 v0.1.1 F-R5 砍：research_brief 调用方构造 |
| per-stage 主模型 | 保留 v0.1.1 F-R7（局部）：orchestrator/sub-agent/write 仍单模型；**仅 judge 豁免**（D-S6 / F-R29） |
| 旧仓完整产物模型 | 保留 v0.1.1 F-R10 砍（局部）：3 阶段最小 schema + SOCM 结构化状态 |
| 下沉 `packages/agent` | D8 禁止：三阶段是业务，留 `competitive_app` |
| SearchOS skills 系统（248 access + 40 strategy） | 砍（D-S9）：公开页 + judge extraction + tavily_fetch 够用 |
| SearchOS TUI（Textual） | 砍（D-S9）：本仓走 FastAPI |
| 多表 + 外键 coverage | 砍（D-S9）：竞争分析单表足够 |
| mid-run steering | 砍（D-S9）：延后 |
| effort 档位（low/medium/high/max） | 砍（D-S9）：env 细粒度先行 |
| 引入 langgraph/langchain/deepagents | 禁（约束 3 + D-S1）：SearchOS 仅架构参考 |

---

## 2. 规范源与角色（locked grill）

| 来源 | 角色 | 约束 |
|------|------|------|
| **SearchOS** `searchos/socm/`（Frontier/Evidence/Coverage/Strategy） | **SOCM 架构参考** | 概念参考；用本仓 pydantic 重写；非代码同构（D-S1） |
| **SearchOS** `searchos/harness/middleware/`（Context/Sensor/Extraction） | **三层中间件架构参考** | 挂本仓 `extensions` runtime 事件（D-S7） |
| **SearchOS** `searchos/agents/orchestrator/` | **coverage 派发循环参考** | 用 asyncio Task 池重写，非 langgraph Send（D-S8） |
| 旧仓 rr-refactor `workflows/competitive/research_brief.py` | **ResearchBrief 结构参考** | 简化（F-R6，不变） |
| 本仓 `earendil_works.pi_agent` | **底座**（Agent/AgentHarness/Session/AbortController/extensions runtime） | 不复制第二内核（G3） |
| 本仓 `earendil_works.pi_ai` | **模型层**（providers/models.streamSimple） | judge 裸调 streamSimple（D-S6） |
| 本仓 `capability_packages/search_*` | **search 阶段搜索工具来源**（tavily/anysearch/grok + `*_fetch`） | 动态挑 search/fetch tool（F-R19 保留） |
| 本仓 `competitive-app-http-v1` | **HTTP 入口**（task 路由不变，投影 schema 变） | 落地后升 v0.3.0 |

**SearchOS 身份（ADR 0010 D-S1）：** 远程 `https://github.com/antins-labs/SearchOS`，本地并排 `SearchOS/`。**仅** v0.2.0 引擎架构参考，**非**代码父本（Pi 父本仍仅为 `earendil-works/pi` main），**非** 1:1 复刻 backlog。

**旧仓身份（D12/ADR 0007）：** 远程 `https://github.com/xj120/competitive-agent`，分支 `rr-refactor`。**仅**业务形状参考。

---

## 3. 落点（locked grill —— 契约 §3.2 / D8）

三阶段代码全部在 `competitive_app/`，**不**碰 `packages/agent`（D8 禁止）：

```text
competitive_app/src/competitive_app/
  domain/
    research_brief.py          # ResearchBrief 简化模型（F-R6，不变）
    stage.py                   # STAGES=(plan,search,write) + StageResult（F-R25）
    socm/
      coverage.py              # Coverage Map：单表 + cell 四态（F-R26）
      evidence.py              # Evidence Graph：findings/sources/confidence + 冲突边
      frontier.py              # Frontier Memory：任务队列 + 优先级 + blocked_by
      strategy.py              # Strategy Memory：策略/失败记忆 + Budget
      state.py                 # SOCM 顶层容器 + 原子写（F-R27）
  application/workflow/
    research_runner.py         # 三阶段 Runner（替换 v0.1.1 六阶段）
    coverage_engine.py         # search 阶段编排：派发/并行/评估/终止（D-S8）
    sub_agent.py               # sub-agent spawn + ContextVar 注入（D-S5/D-S7）
    extraction.py              # EvidenceIntake：judge 调用 + evidence 提交（D-S6/D-S7）
    profiles.py                # per-stage profile（prompt 模板 + tool_names）
    stage_outputs.py           # stage 产物存/取 JSONL（custom_message entry，不变）
  adapter/out/persistence/
    socm_store.py              # search_state.json 原子读写（D-S4）
```

| 层 | 落点 | 约束 |
|----|------|------|
| `domain/` | STAGES / ResearchBrief / StageResult / SOCM 四模型 | 纯，无 fastapi/aiosqlite/pi_agent（G1）；允许 pydantic |
| `application/workflow/` | Runner / coverage_engine / extraction / profiles | 调 pi_agent + adapter/out store；Process Manager |
| `adapter/out/persistence/` | socm_store（JSON 原子写）+ task_projection_store（SQLite） | 只被 application 调 |
| `packages/agent\|ai` | **不改** | 三阶段不下沉 |

---

## 4. 执行模型（locked grill）

### 4.1 plan 阶段（Explore + Schema）

一次 `agent.prompt`：据 brief 的 target+competitors+dimensions，产出搜索计划 + `coverage_schema`（D-S3）。

- LLM 展开维度→属性（如 `pricing`→`免费层/付费起步价/计费单位`），带 fallback + 校验。
- 工具：给 `*_search`（探测 hub 页）+ 可能给 `*_fetch`；**不**给写状态工具。
- 产物非空校验：`plan` 非空 + `coverage_schema` 有 ≥1 实体×≥1 属性。

### 4.2 search 阶段（迭代核心 —— D-S8）

外层编排循环（非单次 prompt）：

```text
读 plan 的 coverage_schema → 初始化 SOCM（空表，cell=empty）
loop:
  1. 评估 coverage：找 empty cell（排除 unknown）
  2. 终止判断：coverage≥阈值 OR 预算耗尽 OR 无进展 → break
  3. 派发：空 cell 打包成 subtask → frontier
  4. 调度：从 frontier 取 subtask，spawn sub-agent（asyncio 池，max_parallel=4）
  5. 等任一完成（FIRST_COMPLETED）→ findings 经 Extraction 进 SOCM
  6. 回 1
终止 → 写 search 阶段汇总产物 → 进 write
```

- **sub-agent**（D-S5）：标准 ReAct（`AgentHarness.prompt` 驱动），拿 subtask（"搜 Notion 的免费层和付费起步价"）→ 调 `*_search` → 调 `*_fetch` 抓页 → Extraction 钩子自动抽 evidence → sub-agent 判断"搜够"结束。**ephemeral**，不落 JSONL。
- **Extraction**（D-S7）：extension 挂 `tool_result`，过滤 `*_fetch`，从 ContextVar 取抽取目标，异步调 judge（批量，一次一个实体所有空 cell），evidence 进 SOCM（原子写）。
- **Sensor**：extension 挂 `tool_call`/`tool_result`，预算计数 + loop 检测（同 query 重复提醒/标记终止）。Sensor 管**单个 sub-agent**，不直接终止 search 阶段。
- **终止三层 OR**（F-R31）：`filled/total ≥ 0.8` / 5 维预算耗尽 / 无进展。

### 4.3 write 阶段（Synthesize）

从 SOCM 合成带 citation 的报告（非从对话）：

- 遍历 coverage map 每个 cell，`filled` 取 value+source，`unknown` 标"未找到可靠来源"，`conflict` 标多源 + 取高 confidence。
- 输出 markdown：实体×属性表 + 每个事实带 `[n]` 脚注 + 末尾 sources 列表。
- 工具：无搜索工具；从 SOCM 读。

### 4.4 per-stage 工具集（F-R8 修订）

一个 harness 跑三阶段（同一 session），每 stage 跑前过滤 `agent.state.tools`：

| stage | 工具 |
|-------|------|
| plan | `*_search`（探测）+ `*_fetch`（抓 hub 页） |
| search | `*_search` + `*_fetch`（sub-agent 用；动态挑 F-R19） |
| write | 无搜索工具 |

### 4.5 数据传递（F-R9 修订）

- **stage 间**：plan→search 传 `coverage_schema`；search→write 传整个 SOCM（evidence graph + coverage map）。仍从 `session.build_context()` 提取 + handler 显式拼 prompt。
- **search 阶段内**：SOCM 是 SoT，sub-agent 经 Extraction 读写，不靠对话传递。

---

## 5. 产物 schema（locked grill —— F-R10 修订）

每 stage 最小 JSON schema，handler 容错解析（失败 → 原始文本塞 fallback 字段，stage 仍算过）：

| stage | 产物 schema |
|-------|------------|
| plan | `{"plan": str, "coverage_schema": {table_id, entities:[...], attributes:[...]}}`（D-S3） |
| search | `{"evidence": list[...], "coverage": {filled:int, total:int, gaps:[...]}}`（汇总快照；过程 evidence 在 SOCM） |
| write | `{"report": str}`（markdown，带 citation） |

产物存进 JSONL `custom_message` entry（`custom_type="stage_output"`，content=产物 dict，details=`{"stage": name}`）——**不变**。SOCM 过程状态（evidence/coverage/frontier）落 `search_state.json`，不进 JSONL（D-S4/D-S5）。

---

## 6. 验收标准（locked）

### 6.1 Offline（默认 CI 必绿）

| ID | 要求 |
|----|------|
| O1 | `ResearchRunner` 跑三阶段（faux model + mock search/fetch tool）→ task `completed`；三 stage 产物全在 JSONL；SOCM 落 `search_state.json` |
| O2 | stage 产物 schema 校验：plan 有 plan+coverage_schema；search 有 evidence+coverage；write 有 report |
| O3 | 依赖门禁：人为让 plan 失败 → search 不跑，task `failed`（reason=dependency_failed） |
| O4 | `GET /tasks/{id}/report` 返回 write 产物（`{task_id, status, stage:"write", report:"<md>"}`）；write 未跑 → `report:null` |
| O5 | `GET /tasks/{id}/sessions` 返回单元素（F-R14，不变） |
| O6 | projection 进度：`GET /tasks/{id}` 返回 `projection.current_stage` + `stages`（3 key）+ `coverage`（filled/total） |
| O7 | abort：`POST /tasks/{id}/abort` 中止在途 task → `aborted`；当前 stage 停 + 后续 stage 不跑（F-R21） |
| O8 | resume 接着跑：failed/aborted task resume → 从第一个非 ok stage 继续 + 恢复 SOCM；completed resume → 返回 completed；running resume → 409（F-R16/F-R18） |
| O9 | 并发 resume 同一 task → 第二个 409（F-R18） |
| O10 | search 终止三层：覆盖率达标 / 预算耗尽 / 无进展 各有测试用例 |
| O11 | coverage cell 四态：empty/filled/unknown/conflict 各有测试用例；unknown 不被重派 |
| O12 | SOCM 原子写：并发 flush 不丢 evidence（per-table 锁） |
| O13 | sub-agent 不落 JSONL：`GET /tasks/{id}/sessions` 仍 1:1；sub-agent findings 只在 SOCM |
| O14 | judge 模型 fallback：不配 `JUDGE_MODEL` 时用主模型；配了用配置模型 |
| O15 | 分层门禁仍绿：三阶段代码落 `competitive_app`，`packages/agent` 无改动；约束 3 AST 扫描仍禁 langgraph/langchain/deepagents |

### 6.2 Live（可选，非 exit-blocking）

| ID | 要求 |
|----|------|
| L1 | `.env` 配真实 provider + 至少一个 search key；`JUDGE_MODEL` 可选（不配则 fallback 主模型）；`POST /tasks` 真跑三阶段打真网；`/report` 返回非空 markdown + 每个事实带 citation |
| L2 | 无 key 时 live skip，不伪绿 |

### 6.3 实现完成定义

- Offline O1–O15 全绿；
- `competitive-app-http-v1` 升 v0.3.0（投影 stages 6→3 + coverage）；
- P1–P3.2 + app http v0.2.0 离线套件无回归（除被替换的 v0.1.1 六阶段测试）；
- v0.1.1 六阶段 runner + 测试已删（PR6）。

---

## 7. 持久化与状态（locked grill —— D-S4）

### 7.1 三层 SoT

| 数据 | 权威 | 落点 |
|------|------|------|
| 三阶段 prompt messages + stage 产物 | **JSONL** @ `data/sessions/--<cwd>--/` | pi_agent `Session.append_custom_message_entry`（D24，不变） |
| **SOCM**（coverage/evidence/frontier/strategy） | **search_state.json** @ `data/sessions/<session_id>/` | `adapter/out/persistence/socm_store.py`（原子写，D-S4） |
| task 状态 + 进度投影（含 coverage 快照） | **SQLite** `tasks.projection_json` | `adapter/out/persistence/`（只读投影） |
| session 索引 | SQLite `sessions` 表 | http feature §5.2（不变） |

### 7.2 projection_json schema（F-R13 修订）

```json
{
  "current_stage": "search",
  "stages": {
    "plan": "ok",
    "search": "running",
    "write": "pending"
  },
  "coverage": {
    "filled": 12,
    "total": 20,
    "pending_cells": 8
  }
}
```

stage status 枚举：`pending` / `running` / `ok` / `failed`（不变）。`coverage` 是 SOCM 的只读快照，runner 在 search 循环每轮更新 SQLite。

### 7.3 终态（F-R15，不变）

| 终态 | 触发 |
|------|------|
| `completed` | 三 stage 全 ok |
| `failed` | stage 验收失败 / 依赖门禁不过 |
| `aborted` | 用户 abort（cancel runner Task + agent.abort，F-R21） |

### 7.4 resume（F-R16 修订）

resume 时：重开 JSONL session（恢复对话）+ 读 `search_state.json`（恢复 SOCM coverage 状态）+ 从第一个非 ok stage 继续。search 阶段中断 resume 时，已 filled 的 cell 不重派，从空 cell 继续。

---

## 8. 决策记录（grill 收敛）

### v0.1.1 决策（24 项；4 项被 v0.2.0 局部反转，余 locked）

| ID | 状态 | 决定 |
|----|------|------|
| F-R1 | locked | 同构旧仓六阶段 `STAGES=(plan,collect,analyze,write,review,cite)` |
| F-R2 | **superseded by v0.2.0 F-R25/F-R31** | ~~统一执行模型：每 stage = 一次 `agent.prompt`；v1 串行~~ → v0.2.0：search 阶段并行 fan-out（D-S8） |
| F-R3 | **superseded by v0.2.0 F-R31（局部）** | ~~严格顺序 + 不补搜~~ → v0.2.0：stage 间仍严格顺序不回退；**search 阶段内**循环补搜（D-S8） |
| F-R4 | locked | stage 产物全进 JSONL（custom_message）；SQLite 存状态/进度/索引 |
| F-R5 | locked | 不加前置 2 接口；research_brief 调用方构造 |
| F-R6 | locked | ResearchBrief 简化：`{target, goal, competitors, dimensions}` |
| F-R7 | **superseded by v0.2.0 F-R29（局部）** | ~~全 task 一个模型~~ → v0.2.0：orchestrator/sub-agent/write 仍单模型；**judge 豁免**用独立模型（D-S6） |
| F-R8 | locked（修订） | 一个 harness 跑三阶段；每 stage 前按 `profile.tool_names` 过滤 tools |
| F-R9 | locked（修订） | stage 间从 `session.build_context()` 提取依赖产物拼 prompt；search 阶段内走 SOCM |
| F-R10 | **superseded by v0.2.0 F-R25/F-R26** | ~~六阶段最小 schema~~ → v0.2.0：三阶段 schema + coverage_schema + SOCM（D-S2/D-S3） |
| F-R11 | locked | review 职责并入 write（从 SOCM 合成时自审）；不触发回退 |
| F-R12 | locked | `GET /tasks/{id}/report` 返回 write 产物 |
| F-R13 | locked（修订） | task.status 四态；进度进 `projection_json`（current_stage + 3-stage status + coverage） |
| F-R14 | locked | task 创建即建 session（1:1）；`GET /tasks/{id}/sessions` 返回单元素 |
| F-R15 | locked | 三终态：completed/failed/aborted |
| F-R16 | locked（修订） | resume 接着跑 + 恢复 SOCM；从第一个非 ok stage 继续 |
| F-R17 | locked | abort 后能 resume |
| F-R18 | locked | 同 task 并发 resume → 409 |
| F-R19 | locked | 默认白名单加 search 包；search 阶段动态挑 `*_search`/`*_fetch` tool |
| F-R20 | locked | system prompt 硬编码 `profiles.py`；不走 capability prompts |
| F-R21 | locked | 双层 abort：agent.abort() 停当前 stage + runner 循环边界检查停后续 |
| F-R22 | locked | 直接替换 v0.1.1 runner；接口不变 |
| F-R23 | locked | feature_id = `research-workflow-v1` |
| F-R24 | locked | 落地后同步升 `competitive-app-http-v1` → v0.3.0 |

### v0.2.0 新决策（7 项，ADR 0010 D-S1..D-S9）

| ID | 状态 | 决定 |
|----|------|------|
| F-R25 | locked | **三阶段** `STAGES=(plan, search, write)` 替换六阶段；analyze/cite 职责并入（D-S2） |
| F-R26 | locked | coverage_schema：单表，LLM 展开维度→属性，type 封闭枚举（text/money_usd/bool/number/enum），cell 四态（empty/filled/unknown/conflict）（D-S3） |
| F-R27 | locked | SOCM = 搜索 SoT，落 `data/sessions/<sid>/search_state.json`（原子写）；SQLite coverage 是只读投影；D24 不变（D-S4） |
| F-R28 | locked | sub-agent ephemeral：findings 进 SOCM，不落 JSONL；1:1 task↔session 不变（D-S5） |
| F-R29 | locked | judge 独立模型（`JUDGE_MODEL` env，默认 fallback 主模型）；局部反转 F-R7；judge 裸调 streamSimple 不走 harness（D-S6） |
| F-R30 | locked | Extraction 挂 extension `tool_result` 事件 + ContextVar 注入抽取目标；judge 批量调（D-S7） |
| F-R31 | locked | search 终止三层 OR：coverage≥0.8（`SEARCH_COVERAGE_THRESHOLD`）/ 5 维预算耗尽（`SEARCH_MAX_QUERIES/FETCHES/ITERATIONS/WALL_SECONDS/OPENS`）/ 无进展（连续 `SEARCH_MAX_STALLED_ITERATIONS=3` 轮 filled 未增）；并行 fan-out（`SEARCH_MAX_PARALLEL=4` 并发 cap，非预算）；env 细粒度不引 effort 档位（D-S8/D-S9） |

---

## 9. 冻结记录

| 项 | 值 |
|----|-----|
| 冻结版本 | `0.2.3` |
| 冻结日期 | 2026-07-30（v0.2.3 patch；v0.2.2 frozen 2026-07-30） |
| grill | 31 决策收敛（§8 F-R1..F-R31；v0.1.1 的 F-R1..F-R24 + v0.2.0 的 F-R25..F-R31）+ v0.2.1 补丁（D-S3'/D-S6'/D-S8'/D-S2a/D-S2b，见 ADR 0010 Patch v0.2.1）+ v0.2.2 补丁（write sections + trace span，见 §9.1）+ v0.2.3 补丁（evidence 物化投影 + clarify brief 推导，见 §9.1） |
| 验收 | §6 Offline O1–O15 + Live L1–L2 |
| 架构影响 | **升 `ARCHITECTURE_CONTRACT` v0.3.5 → v0.3.6**（ADR 0010） |
| Roadmap | 见 `docs/ROADMAP.md` §5（业务能力 v2 研究闭环落地） |
| 关联 | `competitive-app-http-v1` 升 v0.3.0 |

### 9.1 修订

| 版本 | 日期 | 说明 |
|------|------|------|
| 0.1.0 | 2026-07-26 | 草案：六阶段研究 workflow |
| 0.1.1 | 2026-07-26 | **grill frozen**：24 决策；六阶段同构 + 统一一次 prompt + 顺序门禁 + 产物进 JSONL + 简化 ResearchBrief + 单模型 + per-stage 工具 + resume 接着跑 + 替换占位 runner |
| 0.2.0 | 2026-07-28 | **grill frozen（ADR 0010）**：六阶段→三阶段（plan/search/write）；复现 SearchOS coverage 引擎（SOCM + 并行 sub-agent + Extraction + Sensor）；反转 F-R2/F-R3/F-R7/F-R10（局部）；新增 F-R25..F-R31；升架构契约 v0.3.6；`competitive-app-http-v1` 升 v0.3.0 |
| 0.2.1 | 2026-07-29 | **patch frozen（ADR 0010 Patch v0.2.1）**：搜索质量第一步修复——接通 `mark_unknown`（UNKNOWN 状态可达）+ junk/低置信过滤（`_is_junk_value` / `SEARCH_MIN_CONFIDENCE`）+ actionable/satisfied 谓词（`SEARCH_MAX_CELL_ATTEMPTS` / `WEAK_CONFIDENCE`）+ judge prompt 强约束禁占位 + 多源抽取 + plan 结构化 `queries`/`source_hints`（D-S2a）+ subtask 按 `SEARCH_SUBTASK_CHUNK` 拆细（D-S2b）；局部反转 D-S3/D-S6/D-S8 的"一轮单源"默认；对比实验验证两题三阶段搜索质量均显著优于六阶段（源权威性 87%/31% vs 47%/13%、0 junk）；不动 D*/G* 核心、不碰 packages/ai\|agent |
| 0.2.2 | 2026-07-30 | **patch frozen（对齐 VerdaAI 第二批）**：write 产物加 `sections` 字段（后端从 report 按 `##` 切，refine 支持；report 保留向后兼容）+ trace span 记录（plan/subagent/judge/write LLM 调用包夹 emit span → SQLite `task_spans`；轻量：token/latency，无 prompt/response 全文；span 不推 SSE）+ refine stage_output type（append，守 D24；reader 优先 refine 回落 write）；配合 `competitive-app-http-v1` v0.3.2（trace/refine/feedback 接口）；不动 D*/G* 核心、不碰 packages/ai\|agent |
| 0.2.3 | 2026-07-30 | **patch frozen（对齐 VerdaAI 第三批 + 澄清问卷）**：evidence 全量物化投影——任务完成时从 SOCM `evidence_graph.nodes` 扁平化 ACTIVE 节点入 SQLite `evidences` 表（D-S4 投影语义扩展：coverage 计数→evidence 明细；先删后插保 resume 一致；cascade delete 同事务；`brand=entity`/`source_type` 三态派生）；clarify brief 推导——`POST /tasks {query}` 经 1 次 LLM 发现竞品 + 硬编码模板 3 问（融合 VerdaAI：LLM 只发现竞品、问题模板硬编码稳定不漂移）→ `POST /tasks/{id}/clarify` 第 2 次 LLM 推 `ResearchBrief`（强制 competitors≥1，失败 fallback 最小 brief，生问题失败退化直跑）；session 延迟到 clarify 完成才建（F-R14 在启动那一刻成立）；clarify 产物落 `metadata_json`（不建 session、不加表）；配合 `competitive-app-http-v1` v0.3.3（clarify/evidences/dashboard/subscriptions 接口）；不动 D*/G* 核心、不碰 packages/ai\|agent |
