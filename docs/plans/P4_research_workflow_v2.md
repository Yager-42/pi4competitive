# Plan: P4 — Research workflow v2（三阶段 + SearchOS coverage 引擎复现）

| Field | Value |
|-------|--------|
| **plan_id** | `P4-research-workflow-v2` |
| **plan_version** | `0.2.0` |
| **status** | **in_progress**（PR1 文档冻结 done；实现 PR2–PR6 todo） |
| **created** | 2026-07-28 |
| **updated** | 2026-07-28 |
| **roadmap** | [`docs/ROADMAP.md`](../ROADMAP.md) stage **P4** `competitive_app` |
| **contract** | [`docs/contracts/ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.6** |
| **feature** | [`docs/features/research_workflow_v1.md`](../features/research_workflow_v1.md) **v0.2.0 frozen** — `research-workflow-v1`（31 决策 F-R1…F-R31） |
| **ADR** | [0010 research-workflow v0.2.0 SearchOS coverage 引擎](../contracts/adr/0010-research-workflow-v2-searchos-coverage-engine.md) |
| **depends_on** | `research-workflow-v1` v0.1.1 completed（六阶段 runner，待 PR6 删除）；`competitive-app-http-v1` v0.2.0；P1+P2+P3+P3.1+P3.2 done |
| **reference** | [`antins-labs/SearchOS`](https://github.com/antins-labs/SearchOS) `searchos/{socm,harness/middleware,agents/orchestrator}/` — **引擎架构参考**（非代码同构；ADR 0010 D-S1） |
| **target** | `competitive_app/src/competitive_app/{domain/socm,application/workflow,adapter/out/persistence}/` |
| **tests** | `tests/competitive_app/{contract,unit,integration}/`（扩展 + 重写 v1 六阶段测试） |
| **non_goal** | skills 系统；TUI；多表+外键；mid-run steering；effort 档位；引入 langgraph/langchain/deepagents；下沉 packages/agent |

---

## 0. Purpose

1. 复现 SearchOS 的**架构骨架**（SOCM + coverage 派发 + Extraction + Sensor），用本仓 `pi_agent`/`pi_ai` 栈重写，不引其框架依赖（ADR 0010 D-S1）。
2. **六阶段→三阶段** `STAGES=(plan, search, write)`（D-S2 / F-R25），替换 v0.1.1 六阶段 runner。
3. `plan` 产 coverage_schema（实体×属性表）；`search` 迭代填 coverage map（并行 sub-agent + judge 抽 evidence）；`write` 从 SOCM 合成带 citation 报告。
4. SOCM = 搜索 SoT，落 `search_state.json`（D-S4 / F-R27）；JSONL 仍为对话 SoT（D24 不变）；SQLite coverage 是只读投影。
5. resume 恢复 SOCM + 接着跑；abort 双层停（F-R16/F-R21 保留）。
6. 同步升级 `competitive-app-http-v1` → v0.3.0（已在 PR1 契约层完成，PR6 实现层补投影 schema）。

**Approach:** 分期降风险——PR2-5 期间 v2 引擎与 v1 六阶段 runner 并存（实现细节，不破契约）；PR6 删 v1 + 重写测试 + live 验证。每个 PR 对应一个 Phase，按依赖串行。

**Non-goals of this plan:**

| Out of scope | Why |
|--------------|-----|
| skills 系统（248 access + 40 strategy） | D-S9 砍：公开页 + judge + tavily_fetch 够用 |
| TUI / 多表+外键 / mid-run steering / effort 档位 | D-S9 砍 |
| 引入 langgraph/langchain/deepagents | 约束 3 + D-S1 禁 |
| stage 间回退 / stage 内自动 retry | F-R3 保留（search 阶段内循环补搜 ≠ stage 回退） |
| 多角色评审 | F-R11 保留：review 职责并入 write |
| 下沉 `packages/agent` | D8 禁止 |

---

## 1. Binding constraints (contract for implementers)

| ID | Must |
|----|------|
| Feature v0.2.0 | F-R1…F-R31 + §3–§8 — **no inventing open scope** |
| ADR 0010 | D-S1…D-S9 — SearchOS 参考身份 + 9 决策 |
| D8 / §3.2 | 三阶段 + SOCM 落 `competitive_app/`；**不**碰 `packages/agent` |
| G1 / F-A25 | `domain/`（含 `domain/socm/`）无 fastapi/aiosqlite/pi_agent（允许 pydantic） |
| G2 / F-A25 | `adapter/in_/` 只调 application（不改路由层；磁盘目录 `in_` 因 `in` 是 Python 关键字） |
| G3 + 约束 3 | 唯一 agent 内核 = `pi_agent`；**禁** langgraph/langchain/deepagents（AST 扫描） |
| D24 / §7 | 对话 SoT = JSONL；搜索 SoT = `search_state.json`；SQLite = 两者投影 |
| F-R25 | `STAGES=(plan, search, write)`；analyze/cite 职责并入 |
| F-R26 | coverage_schema：单表，LLM 展开维度→属性，type 封闭枚举，cell 四态 |
| F-R27 | SOCM 落 `data/sessions/<sid>/search_state.json`（原子写）；SQLite coverage 只读投影 |
| F-R28 | sub-agent ephemeral：findings 进 SOCM，不落 JSONL；1:1 task↔session 不变 |
| F-R29 | judge 独立模型（`JUDGE_MODEL` env，默认 fallback 主模型）；局部豁免 F-R7 |
| F-R30 | Extraction 挂 extension `tool_result` + ContextVar 注入；judge 批量调 |
| F-R31 | search 终止三层 OR：coverage≥0.8 / 5 维预算 / 无进展；并行 max_parallel=4 |
| F-R16/F-R21 | resume + SOCM 恢复；双层 abort 保留 |

**Prerequisite check (gate G0):**

```bash
.venv/bin/pytest tests/competitive_app tests/packages/agent/contract tests/capability_loader -m "not live" -q
```

---

## 2. 复用的本仓能力（不重造）

| 能力 | 来源 | 用途 |
|------|------|------|
| `Agent` / `AgentHarness` / `agent_loop` | `pi_agent` | plan/write stage prompt + sub-agent ReAct 循环 |
| `extensions` runtime（`tool_call`/`tool_result`/`before_provider_request` 事件） | `pi_agent.extensions` | Sensor（tool_call 预算/loop）+ Extraction（tool_result 抽 evidence）挂载点（F-R30） |
| `wrap_registered_tool` / `ExtensionRunner` | `pi_agent.extensions` | 给 fetch 工具挂 Extraction 钩子 |
| `ModelsImpl.streamSimple` | `pi_ai` | judge 裸调（不走 harness，D-S6）；主模型 stream_fn |
| `Session.append_custom_message_entry` / `build_context` | `pi_agent.harness.session` | stage 产物存/取 JSONL（不变） |
| `AbortController` / `agent.abort` | `pi_agent` | abort（F-R21） |
| `capability_packages/search_*` | `capability_packages/` | search 阶段搜索工具（`*_search` + `*_fetch`，F-R19） |
| `TaskProjectionStore` / `RuntimeRegistry` | `competitive_app` | task 状态/进度 + task active（不变） |
| `JsonlSessionRepo` | `pi_agent` | session 目录（`data/sessions/<sid>/`，SOCM 落其下） |

**参考（不抄）SearchOS：**
- `searchos/socm/{coverage,evidence,frontier,strategy,state,workspace}.py` — SOCM 四件套 + 原子写结构
- `searchos/harness/middleware/{sensor,extraction}/` — Sensor 5 loop 检测 + Evidence Intake 批量 flush
- `searchos/agents/orchestrator/lifecycle.py` — coverage 派发循环 + 并行 sub-agent 调度

---

## 3. 目标文件（新增/修改）

```text
competitive_app/src/competitive_app/
  domain/
    stage.py                        # 改：STAGES=(plan,search,write) + 3 阶段 schema（F-R25/F-R10）
    research_brief.py               # 不变
    socm/                           # 新（Phase A）
      __init__.py
      coverage.py                   # Coverage Map：单表 + cell 四态 + 填充/冲突仲裁（F-R26）
      evidence.py                   # Evidence Graph：findings/sources/confidence + support-conflict 边
      frontier.py                   # Frontier Memory：任务队列 + 优先级 + blocked_by DAG
      strategy.py                   # Strategy Memory：策略/失败记忆 + Budget（5 维）
      state.py                      # SOCM 顶层容器 + snapshot/restore
  application/workflow/
    research_runner.py              # 改：六阶段→三阶段（Phase B）；search 调 coverage_engine
    coverage_engine.py              # 新：search 阶段编排（派发/并行/评估/终止，Phase B+C）
    sub_agent.py                    # 新：sub-agent spawn + ContextVar 注入（Phase C，F-R28/F-R30）
    extraction.py                   # 新：EvidenceIntake（judge 调用 + evidence 提交，Phase D，F-R29/F-R30）
    sensor.py                       # 新：Sensor extension（预算计数 + loop 检测，Phase C）
    profiles.py                     # 改：3 个 profile + system prompt（F-R20）
    stage_outputs.py                # 不变（custom_message 存/取）
    task_service.py                 # 改：resume 恢复 SOCM + DELETE 连带删 SOCM（Phase E）
  adapter/out/persistence/
    socm_store.py                   # 新：search_state.json 原子读写（Phase A，D-S4/F-R27）
    task_projection_store.py        # 改：projection 加 coverage 子字段（Phase E）
  adapter/in_/fastapi/
    dto.py                          # 不变（WorkflowTaskRequest 仍 ResearchBrief）
    routes_tasks.py                 # 不变（路由行为不变，投影 schema 变）
config/settings.example.yaml        # 改：加 SEARCH_* + JUDGE_MODEL env 注释（Phase B）
```

**不改**：`packages/ai|agent`；路由层（14 路由不变）。

**删（Phase E / PR6）**：v0.1.1 六阶段 runner 残留（`research_runner.py` 六阶段逻辑被三阶段替换；`tests/competitive_app/{unit/integration}/test_workflow*.py` 六阶段断言重写）。

---

## 4. 状态板（update as you go）

Status: `todo` | `in_progress` | `done` | `blocked`。

| Step | Phase | Status | Note |
|------|-------|--------|------|
| G0 | v0.1.1 六阶段 + P1–P3.2 离线绿（前置） | done | PR1 前已验证 |
| P1 | 契约冻结：ADR 0010 + workflow v0.2.0 + http v0.3.0 + contract v0.3.6 | done | PR1 |
| A1 | domain/socm/coverage.py：Coverage Map + cell 四态 | done | F-R26 |
| A2 | domain/socm/evidence.py：Evidence Graph + 冲突边 | done | F-R26 |
| A3 | domain/socm/frontier.py：任务队列 + 优先级 + DAG | done | |
| A4 | domain/socm/strategy.py：Strategy Memory + Budget | done | F-R31 |
| A5 | domain/socm/state.py：SOCM 顶层 + snapshot/restore | done | F-R27 |
| A6 | adapter/out/persistence/socm_store.py：原子写 | done | D-S4 |
| A7 | domain/stage.py 改：STAGES=(plan,search,write) + schema | done | F-R25（PR3 切，与 runner/profiles 一起） |
| A7b | v0.1.1 六阶段测试重写为三阶段（unit + integration） | done | PR3 |
| A8 | 契约测试：domain/socm 纯（G1）+ 原子写 + cell 四态 | done | O11/O12 |
| B1 | profiles.py 改：3 profile + system prompt | done | F-R20 |
| B2 | coverage_engine.py：派发循环 + 评估 + 终止（单 sub-agent 串行）+ pause_event 注入点（O6 测试 seam） | done | F-R31 |
| B3 | research_runner.py 改：三阶段主循环 + 门禁 | done | F-R3/F-R25 |
| B4 | coverage_engine：projection coverage 更新（runner re-load merge） | done | F-R13 |
| B5 | settings.example.yaml：加 SEARCH_* + JUDGE_MODEL + CONFLICT_* env 注释 | todo | |
| B6 | 集成测试：三阶段串行跑通（faux） | done | O1/O2 |
| B7 | 重写 v0.1.1 六阶段测试为三阶段（unit + integration） | done | A7b |
| C1 | sub_agent.py：spawn + ContextVar 注入（copy_context） | partial | F-R28/F-R30；ContextVar 留 PR5（Extraction 用） |
| C1b | 契约测试：sub-agent ephemeral（不落 JSONL） | done | O13（build_ephemeral 用 InMemorySessionRepo） |
| C2 | coverage_engine：并行池（max_parallel=4 + FIRST_COMPLETED） | done | F-R31 |
| C3 | sensor.py：预算计数（engine 层 pre-consume query budget + 终止检查） | done | F-R31；extension 化留后续 |
| C4 | sensor.py：loop 检测（同 query 重复） | todo | 挪 PR5（judge Extraction 后 sub-agent 多轮 ReAct 才需要） |
| C5 | 集成测试：并行 fan-out (4 entity) + 预算耗尽 + 无进展终止 | done | O10 |
| D1 | extraction.py：EvidenceIntake（buffer + batch flush） | done | F-R30 |
| D2 | extraction.py：judge 调用（completeSimple + 批量 per entity） | done | F-R29 |
| D3 | extraction.py：挂 tool_result extension + ContextVar 取目标 | done | F-R30 |
| D4 | extraction.py：evidence 进 SOCM（atomic_update）+ coverage fill | done | F-R26/F-R27 |
| D5 | 集成测试：judge 抽 evidence + coverage 填充 + 三态 | done | O11/O14 |
| E1 | write 阶段：从 SOCM 合成带 citation 报告 | todo | F-R12 |
| E2 | task_service：resume 恢复 SOCM + 接着跑 | todo | F-R16 |
| E3 | task_service：DELETE 连带删 SOCM | todo | F-A17 |
| E4 | task_projection_store：projection 加 coverage 子字段 | todo | F-R13 |
| E5 | 删 v0.1.1 六阶段 runner + 重写测试 | todo | F-R22 |
| E6 | 契约测试：约束 3 AST 禁 langgraph + 分层门禁 | todo | O15 |
| E7 | Live 测试（L1/L2，env-gated） | todo | L1 |
| E8 | roadmap/features 索引同步 + plan completed | todo | |

**Rules:**
- Phase A（domain/socm）必须先于 B——B 依赖 SOCM 数据结构。
- Phase B 先串行跑通（单 sub-agent）再进 C 并行——降低调试复杂度。
- Phase D（Extraction）依赖 A（SOCM）+ C（sub-agent ContextVar）。
- v0.1.1 六阶段 runner 在 E5 才删——之前共存不破契约（接口不变）。
- 不改 `packages/ai|agent`。

---

## 5. 分阶段步骤

### Phase A — domain/socm + socm_store（PR2）

**A1. domain/socm/coverage.py** — `CoverageMap`（pydantic，纯）：
- 单表：`table_id`、`entities: list[Entity]`（`id/name/kind`）、`attributes: list[Attribute]`（`id/name/dimension/type/validation`）。
- `cells: dict[(entity_id, attr_id), Cell]`；`Cell` 四态 `empty/filled/unknown/conflict`（F-R26）。
- `filled` 带 `value/source/source_excerpt/confidence`；`unknown` 带 `attempts`；`conflict` 带 `candidates: list`。
- 方法：`fill(entity_id, attr_id, evidence_node)`（仲裁：同 cell 多源 → conflict 或高 confidence 胜）；`mark_unknown()`；`coverage_ratio()`。

**A2. domain/socm/evidence.py** — `EvidenceGraph`：
- `nodes: list[EvidenceNode]`（`id/finding/value/source/source_excerpt/confidence/entity/attribute/page_id`）。
- `edges`：support / conflict（同 entity+attribute 多 node 时）。
- `add_node(node)`（按 signature 去重）。

**A3. domain/socm/frontier.py** — `Frontier`：
- `tasks: list[FrontierTask]`（`id/entity_id/attr_ids/priority:int/blocked_by:list[task_id]/status`）。
- `priority`：int，**越小越高**（0 最高）。
- `blocked_by`：`list[FrontierTask.id]`，空表示就绪；非空则等所列 task 完成才就绪。
- `enqueue(task)` / `dequeue()`：就绪集合（blocked_by 空）中按 priority 升序、同 priority FIFO 取出。
- v0.2.0 **单一 task 类型** `fill`（一个实体 × 它的空 cell 列表）；`backfill` 钩子留作未来多表 feature，v0.2.0 不实现（YAGNI）。

**A4. domain/socm/strategy.py** — `StrategyMemory` + `Budget`：
- `Budget` 5 维消耗预算：`queries`（`*_search` 调用）/ `opens`（页面打开，等价 fetch 计数的别名，`*_fetch`）/ `fetches`（`*_fetch` 调用；v0.2.0 opens 与 fetches 合一计数，留 opens 名以对齐 SearchOS）/ `iterations`（orchestrator 外层轮数）/ `wall_seconds`（墙钟）。每维剩余计数 + `exhausted(dim)`。
- `StrategyMemory`：失败记忆（避免重复死路 query）。

**A5. domain/socm/state.py** — `SOCMState` 顶层容器（`coverage + evidence + frontier + strategy`）+ `snapshot()` / `restore(data)`。

**A6. adapter/out/persistence/socm_store.py** — `SocmStore`：
- `load(session_id) -> SOCMState` / `save(session_id, state)` / `atomic_update(session_id, updater)`。
- 原子写：`asyncio.Lock` + read-modify-write + `os.replace`（tmp 文件）。路径 `data/sessions/<sid>/search_state.json`。

**A7. domain/stage.py 改** — `STAGES=("plan","search","write")`；`STAGE_OUTPUT_SCHEMA` 3 阶段（plan 带 coverage_schema；search 带 evidence+coverage；write 带 report）；`STAGE_DEPENDENCIES`。

**A8. 契约测试** — domain/socm 纯（AST 扫无 pi_agent/fastapi/aiosqlite）；原子写并发不丢；cell 四态各用例。

**Exit A:** SOCM 四模型 + 持久化就位；纯函数可单测；v0.1.1 六阶段仍跑（stage.py STAGES 改了会 break v1 测试——A7 顺带把 v1 测试标 xfail 或挪到 E5 重写，本 Phase 临时共存）。

### Phase B — 三阶段 runner 骨架（串行，PR3）

**B1. profiles.py 改** — 3 个 `StageProfile`：
- plan：`tool_names=None`（动态挑 `*_search`+`*_fetch`）；system prompt 引导建 coverage_schema。
- search：`tool_names=None`（sub-agent 用）；system prompt 引导搜+fetch。
- write：`tool_names=[]`；system prompt 引导从 SOCM 合成。

**B2. coverage_engine.py** — `CoverageEngine`（search 阶段编排，**先串行单 sub-agent**）：
- `run(socm, plan_output) -> search_output`：初始化 coverage（据 plan 的 coverage_schema）→ loop{评估空 cell → 派发 1 个 subtask → spawn 1 sub-agent → 收 findings → Extraction 进 SOCM → 终止判断}。
- 终止三层 OR（F-R31）：`coverage_ratio() ≥ 0.8` / `budget.exhausted(any)` / 无进展（连续 N 轮 filled 未增）。

**B3. research_runner.py 改** — `ResearchRunner.run()` 三阶段：
- plan：`agent.prompt` → 解析 `{plan, coverage_schema}` → 存 JSONL。
- search：调 `CoverageEngine.run(socm, plan_output)` → 存 SOCM + 汇总产物进 JSONL。
- write：`agent.prompt`（prompt 含 SOCM coverage snapshot）→ 解析 `{report}`。
- 依赖门禁 + abort + projection 更新（沿用 v0.1.1 机制，F-R3/F-R21/F-R13）。

**B4.** projection：search 循环每轮更新 `coverage` 子字段（filled/total）。

**B5. 集成测试** — 三阶段串行跑通（faux model + mock search/fetch；单 sub-agent）；O1/O2/O3。

**Exit B:** 三阶段能串行跑通（faux）；并行尚未（C 加）。

### Phase C — 并行 sub-agent + Sensor（PR4）

**C1. sub_agent.py** — `spawn_sub_agent(subtask, context_vars) -> Agent`：
- 用 `copy_context()` 注入 ContextVar（当前实体 + 空 cell 列表，F-R30）。
- sub-agent 是独立 `AgentHarness.prompt` 调用（ephemeral，不落 JSONL，F-R28）。

**C2. coverage_engine 升级并行** — asyncio Task 池（`SEARCH_MAX_PARALLEL=4`）+ `asyncio.wait(FIRST_COMPLETED)` 回收；调度器按 frontier priority 派发。

**C3. sensor.py** — `SensorExtension`（挂 `tool_call` 事件）：
- 预算计数：每次 `*_search`/`*_fetch` 递减 `budget`；触底阻止后续同类工具（让 sub-agent 收尾）。

**C4.** loop 检测：同 sub-agent 重复 query（指纹去重）→ 提醒一次 → 再犯标记该 sub-agent 终止。

**C5. 集成测试** — 并行 fan-out（4 sub-agent 同时）；预算耗尽终止；无进展终止；O10。

**Exit C:** search 阶段并行 + Sensor 就位。

### Phase D — Extraction intake（PR5）

**D1. extraction.py** — `EvidenceIntake`：
- `submit(observation, delivery=BUFFERED)`；buffer 满 `batch_n` 触发 background flush（`_flush_semaphore` 并发上限）。

**D2. judge 调用** — `_run_row_judge(entity, empty_cells, pages)`：
- 裸 `models.streamSimple(model=judge_model, messages=[...])`（D-S6）；judge prompt 引导返回 `[{attribute, value, source_excerpt, confidence}]`。
- `JUDGE_MODEL` env，默认 fallback 主模型（F-R29）。
- 批量：一次一个实体的所有空 cell（D-S6）。

**D3.** 挂 `tool_result` extension：过滤 `toolName in {*_fetch}`（事件字段 camelCase `toolName`，`agent.py:494` emit）→ 从 result details 取页面全文 → 从 ContextVar 取抽取目标 → `evidence_intake.submit()`。sub-agent 退出时 `evidence_intake.flush()`（drain point，防 buffer 丢 evidence）。

**D4.** evidence 进 SOCM：`socm_store.atomic_update` merge 新 evidence → `coverage.fill()`（仲裁 + 冲突标记，F-R26）。

**D5. 集成测试** — judge 抽 evidence（mock judge 返回 JSON）；coverage 填充；四态各用例；judge fallback；O11/O14。

**Exit D:** Extraction 闭环；search 阶段完整。

### Phase E — write + resume + 删 v1 + live（PR6）

**E1. write 阶段** — 从 SOCM 合成：
- 遍历 coverage map：`filled` 取 value+source；`unknown` 标"未找到可靠来源"；`conflict` 标多源。
- 输出 markdown 表 + `[n]` 脚注 + sources 列表（F-R12）。

**E2. task_service resume** — `resume_task`：重开 JSONL session + 读 `search_state.json` 恢复 SOCM + 从 first non-ok stage 继续（search 中断 resume 时已 filled cell 不重派，F-R16）。

**E3. task_service DELETE** — 连带删 `search_state.json`（F-A17）。

**E4. task_projection_store** — `projection_json` 加 `coverage` 子字段（filled/total/pending_cells，F-R13）。

**E5. 删 v0.1.1 六阶段** — `research_runner.py` 六阶段逻辑已被三阶段替换（B3）；重写 `tests/competitive_app/{unit/integration}/test_workflow*.py` 六阶段断言为三阶段；删 v1 plan 引用。

**E6. 契约测试** — 约束 3 AST 扫禁 langgraph/langchain/deepagents；分层门禁；sub-agent 不落 JSONL；O15。

**E7. Live 测试** — 真 provider + search key + `JUDGE_MODEL`；三阶段真跑；`/report` 非空 + citation；L1/L2。

**E8.** roadmap §5 + features/README + agents.md 索引同步；plan `completed`。

**Exit E:** v0.2.0 完整落地；v0.1.1 六阶段已删；live 验证过。

---

## 6. 测试策略

| 层 | 路径 | 断言 | Feature § |
|----|------|------|-----------|
| Unit | `tests/competitive_app/unit/` | STAGES / schema / SOCM 四模型 / cell 四态 | §6.1 O2/O11/O12 |
| Contract | `tests/competitive_app/contract/` | 分层门禁（domain/socm 纯）+ 约束 3 AST + sub-agent 不落 JSONL | §6.1 O13/O15 |
| Integration | `tests/competitive_app/integration/` | 三阶段端到端（faux + mock search/fetch + mock judge） | §6.1 O1/O3–O10 |
| Live（可选） | `tests/competitive_app/integration/live/` | 真网三阶段 + citation | §6.2 L1–L2 |

### 6.1 Offline 测试（默认 CI 必绿，O1–O15）

| ID | 测试 | 构造 + 断言 |
|----|------|------------|
| O1 | `test_three_stages_completed` | faux model（plan 返回 coverage_schema；search mock sub-agent + mock judge；write 返回 report）+ mock search/fetch tool；`POST /tasks` → 202；等 runner 跑完 → `GET /tasks/{id}` status==completed；SOCM 落 `search_state.json`；3 个 stage_output 在 JSONL |
| O2 | `test_stage_output_schema` | plan 有 plan+coverage_schema；search 有 evidence+coverage；write 有 report；缺字段 → stage failed |
| O3 | `test_dependency_gate_failed` | plan 产物空 → search 不跑；task failed；projection.stages.plan=="failed" |
| O4 | `test_report_returns_write_output` | 三阶段跑完 → `/report` → `{stage:"write", report:"<md>"}`；write 未跑 → report==null |
| O5 | `test_task_sessions_single` | `/tasks/{id}/sessions` 单元素；session_id 非 null（F-R14 不变） |
| O6 | `test_projection_progress` | search 中途（注入 `pause_event` 到 CoverageEngine，plan 完成后 search 首轮前阻塞）→ projection.current_stage=="search"；stages.plan=="ok"；coverage.filled/total 更新 |
| O7 | `test_abort_stops_runner` | search 中途 → `/abort` → aborted；write 不跑 |
| O8 | `test_resume_continues` | abort 后 → `/resume` → 恢复 SOCM + 从 search 继续（plan skip）；completed resume → completed；running resume → 409 |
| O9 | `test_concurrent_resume_409` | running 时并发 2 resume → 第二个 409 |
| O10 | `test_search_termination_three_layers` | 覆盖率达标（mock judge 填满至 0.8）/ 预算耗尽（`SEARCH_MAX_QUERIES=2`）/ 无进展（`SEARCH_MAX_STALLED_ITERATIONS=2`，mock judge 持续返回空）各一用例；并行 fan-out（4 sub-agent） |
| O11 | `test_coverage_cell_four_states` | empty/filled/unknown/conflict 各用例；unknown 不被重派；conflict 多源仲裁 |
| O12 | `test_socm_atomic_write` | 并发 flush 不丢 evidence（per-table 锁） |
| O13 | `test_sub_agent_not_in_jsonl` | `/tasks/{id}/sessions` 仍 1:1；sub-agent findings 只在 SOCM |
| O14 | `test_judge_model_fallback` | 不配 `JUDGE_MODEL` → 用主模型；配了 → 用配置模型 |
| O15 | `test_layering_and_no_langgraph` | AST：domain/socm 无 pi_agent；禁 langgraph/langchain/deepagents；`git diff packages/` 为空 |

### 6.2 Live 测试（可选，非 exit-blocking）

| ID | 测试 | 构造 + 断言 |
|----|------|------------|
| L1 | `test_live_three_stages_real` | `.env` 配真实 provider + search key + `JUDGE_MODEL`；`POST /tasks` 真跑三阶段打真网；`/report` 非空 markdown + 每个事实带 citation；status==completed |
| L2 | `test_live_skip_without_key` | 无 key 时 live skip |

### 6.3 命令

```bash
.venv/bin/pytest tests/competitive_app -m "not live" -q          # offline
.venv/bin/pytest tests/competitive_app/contract -q               # 分层门禁（快）
.venv/bin/pytest tests/competitive_app -m live --maxfail=1       # live
ruff check . && ruff format .                                     # lint
```

---

## 7. 风险

| Risk | Mitigation |
|------|------------|
| SearchOS 概念搬过来和 `pi_agent` 栈阻抗（langgraph Send → asyncio 池） | D-S1/langgraph 映射附录已列机械替换；B 先串行跑通再 C 并行 |
| judge 成本是搜索乘子（每页每实体一次 LLM） | F-R29 批量调 + `JUDGE_MODEL` 可配便宜模型；默认 fallback 主模型不增配置 |
| SOCM 三层 SoT（JSONL + search_state.json + SQLite）一致性 | D-S4 原子写 + SQLite 是只读投影；resume 优先读 SOCM |
| sub-agent ContextVar 跨 asyncio Task 丢失 | C1 用 `copy_context()` 显式注入（对应 SearchOS `set_current_table`） |
| coverage_schema LLM 展开乱来 | F-R26 校验（≥1 实体×≥1 属性，attr id 唯一，dimension 来自 brief）+ fallback |
| search 终止条件不严（死循环 or 过早进 write） | F-R31 三层 OR + `unknown` 态防重派 + Sensor loop 检测 |
| Extraction 挂 tool_result 影响所有工具调用 | D3 过滤 `tool_name in {*_fetch}` |
| v0.1.1 六阶段测试在 A7 改 STAGES 后 break | A7 临时标 xfail 或挪 E5 重写；E5 一次性清 |
| 并行 sub-agent 共享 tavily key 限速 | `SEARCH_MAX_PARALLEL=4`（保守，可配） |
| 环境无 uv | `.venv/bin/pytest` 直接用；交付后 `uv run pytest` |

---

## 8. Definition of Done

- [ ] §4 状态板 G0–E8 = `done`
- [ ] Feature §6.1 Offline O1–O15 全绿
- [ ] `competitive-app-http-v1` v0.3.0 实现层补齐（projection coverage 子字段）
- [ ] P1–P3.2 + app http 离线套件无回归（除 E5 重写的 v1 测试）
- [ ] `packages/agent|ai` 零改动（git diff 空）
- [ ] 约束 3 AST 扫描禁 langgraph/langchain/deepagents 绿
- [ ] 14 路由不变（行为变真）
- [ ] v0.1.1 六阶段 runner + 测试已删（E5）
- [ ] L1 live 验证过（真 provider + search + judge；三阶段全 ok；报告带 citation）

---

## 9. 与后续 feature 的边界

```text
本 feature：三阶段研究 workflow（plan/search/write + SearchOS coverage 引擎）
后续 1：mid-run steering（search 跑时注入用户约束）
后续 2：effort 档位（low/medium/high/max 一键调参）
后续 3：多表 + 外键 coverage（开放域问题）
后续 4：skills 系统（反爬/登录墙站点）
后续 5：报告图表 / chart_requirements
```

本 feature 留稳定 `CoverageEngine.run(socm, plan_output)` + `SocmStore` 接口，使后续能扩展（steering / 多表 / skills）而不改三阶段外壳。

---

## 10. 修订记录

| Version | Date | Note |
|---------|------|------|
| 0.2.0 | 2026-07-28 | 草案：三阶段研究 workflow（SearchOS coverage 引擎复现；ADR 0010）；5 Phase（A domain/socm / B runner 骨架 / C 并行+Sensor / D Extraction / E write+resume+删v1+live）；offline O1–O15 + live L1–L2；PR1 契约冻结 done，实现 PR2–PR6 todo |
