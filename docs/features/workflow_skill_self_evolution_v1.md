# Feature Contract：workflow-skill-self-evolution-v1

| 字段 | 值 |
|------|-----|
| **feature_contract_version** | `0.2.1` |
| **status** | **frozen — G1–G29 resolved；implementation completed and verified by plan v0.1.0** |
| **created** | 2026-07-30 |
| **updated** | 2026-07-30 |
| **feature_id** | `workflow-skill-self-evolution-v1` |
| **roadmap_stage** | **P4** `competitive_app` 业务能力；feature frozen and implemented；verification complete |
| **architecture_contract** | [`ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.6**（D5/D8/D9/D10/D22/D24/D25；不修改 D*/G*） |
| **depends_on** | [`research-workflow-v1`](research_workflow_v1.md) v0.2.2；[`agent-engine-extensions-v1`](agent_engine_extensions_v1.md) v0.3.0；P3 local capability loader |
| **参考实现（代码父本）** | [`HezaoHezao/poirot`](https://github.com/HezaoHezao/poirot/tree/86bf279ad90c180f0ba696755620dd7d6661465e) frozen SHA [`86bf279`](https://github.com/HezaoHezao/poirot/commit/86bf279ad90c180f0ba696755620dd7d6661465e) |
| **许可证** | Poirot MIT；直接复制或实质改编的文件必须保留来源、copyright 与 MIT notice |
| **path** | `docs/features/workflow_skill_self_evolution_v1.md` |
| **plan** | [`P4_workflow_skill_self_evolution.md`](../plans/P4_workflow_skill_self_evolution.md) **v0.1.0 completed** |

---

## 0. 效力与当前状态

1. 本文是 `workflow-skill-self-evolution-v1` 的冻结 feature contract，本文中的 MUST/SHALL/禁止项具有实现约束力。
2. G1–G29 已全部关闭；实现计划不得重新解释或静默扩大边界。
3. 生产实现只能在单独实现计划建立后开始；计划必须逐项映射本文 module map、host delta、数据和验收边界。
4. 本 feature 的核心约束是 **transplant-first**：尽可能直接移植冻结 Poirot SHA 的 Skill 自进化代码；只有融入当前架构确有必要时才 ADAPT/REWRITE。
5. 本 feature 不改变架构契约：业务策略、反思、评价、版本生命周期仍落 `competitive_app`；生成 Skill 落本地 `capability_packages/`；不修改 `packages/ai|agent` 边界。
6. 后续若需改变 D*/G*、引入第二 Agent 内核、改变 Pi Skill/extension 公共语义，必须先新增 ADR 并升级架构契约；其他边界变化至少升级本文版本。

---

## 1. 动机与目标

### 1.1 问题

CompetitorLens 的流程骨架固定为：

```text
plan → search → write
```

固定的是：

- stage 顺序与依赖；
- SOCM coverage/evidence 状态；
- 并行 sub-agent 调度；
- budget、termination、abort、resume；
- stage 输出 schema；
- evidence/citation 真相源。

不固定的是 LLM 在各 stage 内采用的策略，例如：

- 如何拆比较属性；
- 如何构造和改写 query；
- 如何定位权威来源；
- 如何处理同名产品、动态网页、地区和货币；
- 如何从页面抽取、标准化和仲裁冲突值；
- 如何在不虚构事实的前提下组织报告。

同类问题在不同任务中反复出现时，当前系统会让 LLM 每次重新推理，没有将已验证解法沉淀为可复用 Skill。

### 1.2 核心目标

1. 将三阶段固定 workflow 视为一个**概念上的基础 Skill**，但不把 Application Process Manager 攊平为 Pi Skill。
2. 只对未被 harness/feature contract 固定的策略部分生成 learned Skill overlay。
3. 任务结束后从 JSONL、SOCM、task projection、span、feedback/refine 中识别问题和有效解法。
4. 复用 Poirot 的完整闭环：

```text
select/inject/metrics
        ↓
trigger → focus → mutate → evaluate → gate
        ↓
version DAG → activate → runtime tracking → rollback
```

5. candidate 必须通过移植自 Poirot 的 EvalBridge + ScoreDeltaGate 才可激活；激活后退化可回滚。
6. 新版本只影响后续任务；在途任务和 resume 固定使用原 Skill version set。
7. 最大限度保持 Poirot 的模块、类型、类名、算法、数据字段和调用次序，所有 host delta 必须逐项记录。

### 1.3 非目标

| 不做 | 原因 |
|------|------|
| 把 `ResearchRunner`/`CoverageEngine` 改成 Skill | 违反 D8/D9；状态机不是 prompt 资源 |
| 允许 Skill 修改 STAGES/SOCM/budget/termination/schema | 破坏冻结 workflow 不变量 |
| 搬 Poirot 的 LangChain/LangGraph Agent 内核 | 第二内核；违反架构契约 |
| 搬 Poirot TUI/CLI/Skill Hub/MCP/Sandbox/Memory/Multi-Agent | 与本 feature 无关 |
| 修改 `packages/ai|agent` 承载竞品业务 policy | 违反 D8 和 Pi 父本边界 |
| 远程安装或在线拉取 Skill | D22 仅本地 capability packages |
| 单次反思后直接覆盖 active Skill | 绕过 Poirot eval/gate/version/rollback，风险不可控 |
| 运行中热切换 Skill 版本 | 破坏可复现性与 resume |
| 另建 `reflection.db` / `skills.db` | App operational state 继续共享 `data/app.db` |
| 另建 workflow benchmark/replay 机制 | 冻结 Poirot 父本没有该机制；本 feature 不自行补设计 |

---

## 2. 术语与固定边界

### 2.1 Skill 与 Extension

当前 Pi 语义：

- **Skill**：`SKILL.md` prompt/resource，由 `pi_agent.harness.skills` 加载并注入上下文；
- **Extension**：运行时事件处理器，可处理 `tool_call`、`tool_result` 等事件；
- **Capability package**：本地容器，可同时提供 `skills/`、`extensions/`、tools、prompts。

本 feature 不把 Skill 与 Extension 混为同一类型。learned Skill 是 Skill resource；若需要工具级 provenance/metrics，复用现有 extension runtime，不发明平行 hook。

### 2.2 Base Workflow 与 Learned Overlay

```text
Base workflow（冻结）
  plan/search/write + SOCM + runner + tool boundary

Learned overlays（可进化）
  plan strategy
  search strategy
  extraction strategy
  write strategy
```

Base workflow 不创建 `SKILL.md`，也不进入 Skill version DAG；“整个固定流程是一个 Skill”只作为概念模型。其唯一真相仍是代码、stage profiles、SOCM 与 feature contract，且不参与自动 mutation。learned overlay 必须声明 `scope`，只能影响对应 prompt/strategy slot。

### 2.3 可进化范围（G5 resolved）

`SkillScope` 固定为 `plan | search | extraction | write`。scope 表示独立注入、归因和评价边界，不等同于 workflow stage；`extraction` 仍是 search 内部子能力，不新增 stage。

| scope | 可进化 | 不可进化 |
|-------|--------|----------|
| `plan` | 属性拆解、query 模板、source hint、领域比较框架 | plan schema、entity/attribute 基本不变量 |
| `search` | query rewrite、来源优先级、消歧、fallback、停止搜索策略提示 | 工具白名单、并行池、budget、termination |
| `extraction` | 值标准化、类型解释、冲突提示、页面定位提示 | Evidence/SOCM schema、grounding 要求 |
| `write` | 章节组织、unknown/conflict 表达、结论组织 | citation、SOCM-only facts、write schema |

---

## 3. Transplant-first 原则（核心需求）

### 3.1 默认规则

1. 采用**迁移式照抄（transplant-first）**：没有架构冲突、无需重写的 Poirot 代码直接复制；为融入当前架构确有必要时允许适配或重写，但不得无理由自行设计替代机制。
2. 保持：
   - 模块拆分；
   - 类名和主要方法名；
   - dataclass/value-object 字段；
   - version DAG 语义；
   - trigger→focus→mutate→eval→gate→record 次序；
   - anti-loop/cooldown 算法；
   - fail-closed promotion gate；
   - runtime degradation rollback。
3. 每个移植文件头记录：
   - upstream URL；
   - upstream SHA；
   - 原始路径；
   - MIT attribution；
   - host delta 列表。
4. 实现计划必须附逐文件 module map，并区分：
   - `COPY`：无需语义改变，直接复制，允许 import/包路径等机械调整；
   - `ADAPT`：保留主体算法和控制流，替换框架、IO 或接口；
   - `REWRITE`：当前架构无法合理容纳原实现，允许重写；必须说明冲突、保留的上游行为契约和 parity 验证；
   - `OMIT`：明确不搬；
   - `NEW-HOST`：当前架构必需且 Poirot 无对应物。
5. 审计采用 module map + 每文件 upstream provenance + host-delta/rewrite rationale；逐文件 diff 是评审辅助证据，不作为必须提交的永久 artifact；不设置文本相似度阈值。
6. 能直接复制的代码不得仅以“更符合本仓风格”为理由重写；需要重写时以当前架构正确性优先，不为追求表面相似而保留不合适的 LangChain、同步 IO 或独立 DB 边界。
7. 合理差异包括但不限于：LangChain→Pi、通用任务→竞品 workflow、独立 DB→app.db、同步 LLM→async Pi API；每项差异仍须可审计。

8. **命名边界（G3 resolved）**：目标目录服从本仓 `domain/application/adapter` 分层；语义未改变的 Poirot 模块叶子名、类名和核心方法名尽量原样保留（如 `EvolutionManager`、`IVEFocuser`、`LLMMutator`、`ScoreDeltaGate`、`GitRatchet`）；host glue 或语义已改变的对象按本仓职责命名。
9. **异步边界（G4 resolved，代码/架构已决定）**：当前 `pi_ai.complete*`、`AgentHarness.prompt`、extension emit、`ResearchRunner.run` 均为 asyncio 链路，因此任何触达 LLM、DB、文件或 workflow 的同步 Poirot 调用必须机械改为 async/await；纯 dataclass、纯计算、阈值判断和无 IO store mapping 保持同步。禁止在事件循环内用同步阻塞包装来追求源码表面一致。

### 3.2 参考 SHA

Poirot 唯一代码父本冻结为 `86bf279ad90c180f0ba696755620dd7d6661465e`。实现、COPY/ADAPT 审计、测试夹具和 attribution 均以该 immutable SHA 为准。

后续 Poirot `master` 的变化不得静默混入；若希望吸收上游修复，必须单独提出 source rebase，审阅 frozen SHA→新 SHA 的 upstream diff，并升级本 feature contract/source module map。

**RESOLVED-P1 / G1：冻结当前 SHA；实现期不追随 `master`。**

---

## 4. Poirot 搬运清单与目标映射（冻结 module map）

> 本节冻结搬运范围与差异类别，不替代实现计划；实现计划仍须逐文件复核 upstream 源码、许可证和 host delta。

### 4.1 Layer 1：Skill 基础层

| Poirot 源文件 | 搬运档 | 本仓目标落点 | 预期 host delta |
|---------------|--------|--------------|-----------------|
| `agents/skill/types.py` | `COPY` | `competitive_app/domain/evolution/skill_types.py` | 增加/映射 workflow scope；其余字段尽量不变 |
| `agents/skill/store.py` | `ADAPT` | `adapter/out/persistence/learned_skill_store.py` | 复用 `data/app.db` 连接/迁移；不另开 DB；保留表语义和 CRUD |
| `agents/skill/parser.py` | `COPY` | `application/evolution/poirot_port/parser.py` 或 capability 资源侧 | import path 和 metadata 字段适配 |
| `agents/skill/injector.py` | `ADAPT` | `application/evolution/skill_injector.py` | 输出 Pi system-prompt composition，不产 LangChain Message |
| `agents/skill/selector.py` | `ADAPT` | `application/evolution/skill_selector.py` | LLM transport 改 `pi_ai`；按 G7 改为 per-scope 延迟选择并 task-pinned |
| `middlewares/skill_metrics_middleware.py` | `ADAPT` | `application/evolution/skill_metrics.py` + 可选现有 Pi extension | 去 LangChain middleware；工具 provenance 走已有 extension events |
| `middlewares/skill_injection_middleware.py` | `ADAPT` | `ResearchRunner`/`CoverageEngine` prompt composition adapter | 不复制 AgentMiddleware 外壳；保留 selection/provenance 次序 |

### 4.2 Layer 2：Evolution

| Poirot 源文件 | 搬运档 | 本仓目标落点 | 预期 host delta |
|---------------|--------|--------------|-----------------|
| `skill/evolution/types.py` | `COPY` | `domain/evolution/evolution_types.py` | 尽量零语义差异；必要时加 evidence ref 类型 |
| `skill/evolution/protocols.py` | `COPY` | `application/evolution/protocols.py` | import path |
| `skill/evolution/manager.py` | `ADAPT` | `application/evolution/evolution_manager.py` | 同步 LLM 链改 async；编排次序不变 |
| `evolution/triggers/metric_monitor.py` | `COPY+ADAPT` | `application/evolution/triggers/metric_monitor.py` | 保留 Poirot metrics 与 5/0.3/10 阈值；store 改 app.db adapter |
| `evolution/triggers/capture_trigger.py` | `OMIT` | — | G13 删除 manual capture；自动 CAPTURED 由 post-task host observation 产 context |
| `evolution/focus/ive_focuser.py` | `ADAPT` | `application/evolution/focus/ive_focuser.py` | LLM adapter；failure evidence 接 JSONL/SOCM refs |
| `evolution/mutators/llm_mutator.py` | `ADAPT` | `application/evolution/mutators/llm_mutator.py` | staging root、async LLM、frontmatter scope；diff/budget 算法尽量保持 |
| `evolution/gates/score_delta_gate.py` | `COPY` | `application/evolution/gates/score_delta_gate.py` | 原样保留 min_delta=0、CAPTURED score>0、hard-failure reject |
| `evolution/gates/git_ratchet.py` | `COPY+ADAPT` | `application/evolution/gates/git_ratchet.py` | store adapter；仍是 active pointer rollback，不执行 git 命令 |
| `evolution/eval/programmatic_bridge.py` | `COPY` | `application/evolution/eval/programmatic_bridge.py` | 保留父本 facade；eval disabled 时使用，enabled 时由 RegistryEvalBridge 替换 |

### 4.3 Layer 3：Eval

| Poirot 源文件 | 搬运档 | 本仓目标落点 | 预期 host delta |
|---------------|--------|--------------|-----------------|
| `skill/eval/types.py` | `COPY` | `domain/evolution/eval_types.py` | 不增加 benchmark protocol/model/provider identity |
| `skill/eval/registry.py` | `COPY+ADAPT` | `application/evolution/eval/registry.py` | import path；注册方式保持 instance-level |
| `eval/analyzers/checks.py` | `COPY` | `application/evolution/eval/checks.py` | 对 Skill 静态规则直接复用 |
| `eval/analyzers/contract_compiler.py` | `COPY` | 同名 target | 保持规则编译语义 |
| `eval/analyzers/response_contract_checker.py` | `COPY+ADAPT` | 同名 target | 保留 Poirot 静态门；仅做 import/host 数据适配，不追加 workflow hard gate |
| `eval/analyzers/skill_judgment_analyzer.py` | `ADAPT` | 同名 target | LangChain→pi_ai；journal/messages 接 JSONL/SOCM/span |
| `eval/analyzers/task_quality_judge.py` | `ADAPT` | 同名 target | 保留 Poirot post-execution 四维评分与权重；LangChain→pi_ai；只存 task quality，不进入 promotion score |
| `skill/eval/runtime_tracker.py` | `COPY+ADAPT` | `application/evolution/eval/runtime_tracker.py` | store 接 app.db；保留 window=20、degradation_delta=0.15 和 advisory 语义 |

### 4.4 明确不搬

| Poirot 模块 | 决定 | 原因 |
|-------------|----------|------|
| LangGraph graph/runtime | `OMIT` | 本仓 Pi 是唯一 Agent 内核 |
| `AgentMiddleware` 外壳 | `OMIT` | 映射到 ResearchRunner/Pi extension，不引第二事件系统 |
| Poirot `LeaderAgent` | `OMIT` | 已有 ResearchRunner/CoverageEngine |
| memory 五层 | `OMIT` | 非本 feature；JSONL/SOCM 已是证据来源 |
| multiagent/sandbox/MCP | `OMIT` | 非本 feature |
| TUI/CLI/Skill commands | `OMIT` 或后续另 feature | 当前产品走 FastAPI；本契约不扩 HTTP 面 |
| `.poirot/skills.db` | `OMIT` | 复用 `data/app.db` |
| Poirot builtin 36 skills | `OMIT` | 本 feature 只生成竞品 workflow learned skills |

### 4.5 必须新增的 Host Glue

以下是 Poirot 无法直接提供、但在当前架构中必要的最小 glue：

1. `PiLlmAdapter`：把 Poirot analyzer/mutator 所需调用映射到 `pi_ai` async API。
2. `WorkflowEvidenceAdapter`：将 JSONL/SOCM/span/feedback 变成 Poirot `FailureEvidence`/evaluation input。
3. `StageSkillComposer`：把 selected Skill 注入 plan/search/extraction/write 对应 prompt。
4. `SkillVersionSnapshot`：任务创建时固定 Skill version set，resume 复用。

Host glue 不得包含另一套 evolution 算法。

---

## 5. 当前接入缺口（已观察事实）

### 5.1 Main harness 的 Skill prompt 被 stage profile 覆盖

`apply_capability_report()` 会把 `report.skills` 合入初始 system prompt；但 `ResearchRunner._build_prompt()` 当前直接执行：

```python
self.agent.state.systemPrompt = profile.system_prompt
```

因此 plan/write stage 不保证继续携带 capability Skill 内容。

### 5.2 Search ephemeral sub-agent 未加载 Skill

`_HarnessFactory.build_ephemeral()` 当前只传 tools，并挂 Extraction extension；`CoverageEngine._run_subagent_prompt()` 又直接设置 `_SEARCH_RUNTIME_PROMPT`。search sub-agent 没有 selected Skill 输入。

### 5.3 第一实现门

在开始 mutation/versioning 前，必须先证明：

- plan Skill 能进入 plan prompt；
- search Skill 能进入每个 ephemeral sub-agent prompt；
- extraction Skill 能进入 judge extraction prompt；
- write Skill 能进入 write prompt；
- 同一任务在 resume 后仍使用相同版本；
- 未选择的 Skill 不进入 prompt。

该修正位于 `competitive_app` prompt composition，不要求修改 Pi core。

---

## 6. 冻结落点与依赖方向

```text
competitive_app/src/competitive_app/
  domain/evolution/
    skill_types.py
    evolution_types.py
    eval_types.py

  application/evolution/
    evolution_manager.py
    skill_selector.py
    skill_injector.py
    protocols.py
    triggers/
    focus/
    mutators/
    gates/
    eval/
    adapters/
      pi_llm.py
      workflow_evidence.py

  adapter/out/persistence/
    learned_skill_store.py

capability_packages/learned_skills/
  package.json
  skills/
    <skill-id>/
      SKILL.md
      .skill_id
```

冻结依赖：

```text
competitive_app.application.evolution
  → competitive_app.domain.evolution
  → adapter/out ports
  → pi_agent Skill resource APIs
  → pi_ai model API

capability_packages/learned_skills
  → generic local loader only
  ↛ competitive_app.domain
```

`domain/evolution` 必须无 FastAPI、aiosqlite、pi_agent、pi_ai 和文件 IO。

---

## 7. 状态与真相源

### 7.1 保持现有 SoT

| 数据 | 权威来源 |
|------|----------|
| agent 对话/tool transcript | JSONL session |
| search coverage/evidence/frontier/strategy | `search_state.json` SOCM |
| task 状态/trace/feedback | `data/app.db` |
| Skill 内容 | `capability_packages/learned_skills/**/SKILL.md` |
| Skill catalog/version/metrics/eval/promotion | `data/app.db` |

SQLite 只存 JSONL/SOCM 引用，不复制完整 transcript 形成第四份事实源。

### 7.2 Poirot schema 复用

Poirot 表/字段按冻结父本原样放入现有 `data/app.db`：

- `skill_records`；
- `skill_lineage_parents`；
- `skill_judgments`；
- `skill_evolutions`；
- `skill_eval_judgments`；
- `task_quality_scores`；
- `skill_eval_runs`。

必要的 host-only 表/字段：

- `skill_task_bindings`：task→固定 version set；
- `skill_observations`：problem signature + evidence refs；
- `scope`：plan/search/extraction/write；

**RESOLVED-P2 / G20：原表照搬 + companion tables。** `skill_records`、lineage、judgments、evolutions、task quality、eval runs 等保持 Poirot schema/CRUD 语义；`workflow_skill_metadata`、`skill_task_bindings`、`skill_observations` 等 host-only 数据放旁表，以 `skill_id/task_id` 关联，不向上游原表塞 workflow 字段。

### 7.3 Skill 文件与版本命名（G21 resolved）

1. 保留 Poirot skill id/name 规则：`{name}__cand_{uuid8}`、`{name}__v{generation}_{uuid8}`、`.skill_id` sidecar 和 16 位 content hash 语义；
2. candidate、active 和历史版本全部保留在 `capability_packages/learned_skills/skills/<skill-id>/SKILL.md`；
3. `capability_packages/learned_skills/package.json` 的 `pi.skills` 由 App 原子维护，只显式列出每个 Skill name 当前唯一 active（已通过 gate 的最新激活版本）；
4. candidate 和 inactive history 虽在 `skills/` 目录内，但不得进入 manifest，因此 Pi loader/catalog 不加载；
5. promotion/rollback 必须在同一临界区内先完成文件与 DB active pointer，再原子替换 manifest；失败时 fail closed，不能暴露 candidate 或多个同名版本；
6. 不修改 `packages/agent` loader 查询 `app.db`。

### 7.4 Task deletion（G22 resolved）

删除 research task 时继续删除现有 task/session JSONL/SOCM/spans/feedback，并额外删除该 task 的 `skill_task_bindings`、尚未消费的 `skill_observations` 及原始 evidence refs。已经形成的 Skill versions、evolution records、聚合 metrics，以及不含原始 transcript/SOCM 内容的 judgment/task quality score 保留；其中 task/run 外键或引用必须置空/去标识，不能成为悬空可解析引用。删除 task 不自动删除或回滚已激活 Skill。

### 7.5 Candidate retention（G23 resolved）

通过 gate 的 candidate 作为 version 永久保留；被 ScoreDeltaGate reject、eval exception 或 mutation failure 拒绝的 candidate，在 EvolutionRecord（含 candidate_id、diff、score、decision、reason）成功写入后立即删除其 `SKILL.md`、`.skill_id` 和空目录。若 EvolutionRecord 写入失败则 fail closed，先保留文件供恢复，不执行删除。被拒绝 candidate 从不进入 package manifest。

### 7.6 Concurrency（G24 resolved）

为保持 Poirot 同步 `EvolutionManager.run_cycle()` 的串行语义，v1 在单 App 进程内使用一个 global `asyncio.Lock` 串行所有 FIX/CAPTURED evolution cycle。获取锁后必须重新扫描 trigger、metrics 和 active pointer，不能使用等待锁前的 stale context。v1 不支持多个 App 进程同时写同一 `app.db`/learned-skills root，不引入 per-skill lock、CAS 或 distributed lock。

### 7.7 Crash recovery（G25 resolved）

完全沿用 Poirot：不持久化 evolution job step，不恢复中断的 focus/mutate/eval/gate，不做启动对账，不重建 manifest，不自动清理 crash 遗留 orphan candidate。服务重启后只按正常 bootstrap 读取当时已持久化的 DB/文件状态；后续 trigger 可发起新 cycle。该选择接受 Poirot 原有的 crash window，不为其补充恢复状态机。

---

## 8. 运行闭环

### 8.1 按 scope 延迟选择并固定（G7 resolved）

1. 任务创建/首次进入 plan 时，从 active skills 选择并绑定 `plan` versions；
2. plan 完成、首次进入 search 时，使用 ResearchBrief + plan 输出选择并绑定 `search` 与 `extraction` versions；
3. search 完成、首次进入 write 时，使用 ResearchBrief + SOCM 结果选择并绑定 `write` versions；
4. 每个 scope 首次选择后立即写 `skill_task_bindings`，该任务内永久固定；
5. resume 复用已有 bindings；仅尚未首次进入、没有 binding 的 scope 可以执行首次选择；
6. 运行中的 promotion/rollback 不改变已绑定任务；
7. selection/provenance 按 Poirot 语义打点。

### 8.2 任务结束后的 reflection

仅 `completed` 与 `failed` 任务参与 post-task observation、Skill 指标和 mutation trigger。`aborted` 完全忽略，不生成 observation，不计 selection outcome/fallback/completion，也不作为 eval evidence；避免把用户取消或外部中断误归因于 Skill。

证据来源：

- stage status/error；
- coverage empty/unknown/conflict/weak/junk；
- stalled/budget exhausted；
- query/fetch/tool errors；
- evidence authority/confidence；
- citation completeness；
- spans/token/latency；
- report feedback/refine。

### 8.3 Problem signature

LLM 可归纳问题，但输出必须归一化为稳定 signature，例如：

```text
search.source_discovery.saas_pricing
search.entity_disambiguation.same_name
extraction.money.annual_monthly
write.claims.unknown_overclaim
```

### 8.4 FIX Trigger（G10 resolved）

已有 active Skill 的 `FIX` 完整沿用 Poirot MetricMonitor 的触发语义与默认值：

- `min_selections=5`；
- `evolve_threshold=0.3`；
- `cooldown_selections=10`，即一次触发后至少新增 10 次 selection 才能再次触发；
- 保留 fallback/applied/completion/effective rate 计算；
- 保留 optional LLM confirmation。

G10 不约束新 Skill 的 `CAPTURED` 首次生成条件；该边界由 G11 单独决定。

### 8.4.1 CAPTURED Trigger（G11 resolved）

v1 保留 Poirot `CAPTURED`，用于创建此前不存在的新 Skill。单次 `completed` 或 `failed` 任务只有在 evidence 中同时具备以下条件时，才生成 inactive candidate：

1. 可指向具体 JSONL/SOCM/span/feedback 的问题证据；
2. 任务轨迹中存在实际奏效的解决步骤，而不是反思模型臆测的解法；
3. IVE/transferability 判断表明该解法可跨任务复用；
4. 与现有 active/candidate Skill 去重后仍是新能力。

只发现问题但没有已验证解法时，仅累计 observation，不生成 candidate。证据满足时不要求同一 signature 先出现三次；candidate 仍须通过 Poirot EvalBridge + ScoreDeltaGate 才能激活。

### 8.4.2 DERIVED（G12 resolved）

冻结 Poirot SHA 的 `EvolutionManager` 明确只实现 `FIX + CAPTURED`，并标注“DERIVED 留 2b”；冻结父本没有 DERIVED trigger、合并算法或 evaluation 语义。本 feature 因此不自行补设计 DERIVED：v1 不生成、不激活、不暴露 DERIVED 操作。若为直接复制上游 value object 而保留 `DERIVED` Literal，它仅是不可达的兼容值，不构成本 feature 能力；后续启用必须另立 feature contract。

### 8.4.3 Manual Capture（G13 resolved）

v1 完全删除 manual capture 能力：不移植/暴露 `EvolutionManager.capture_skill()` 与 `CaptureTrigger.manual_capture()`，不新增 HTTP、CLI、UI 或内部 application command。`CAPTURED` 只能由符合 G11 证据条件的 post-task 自动闭环产生，且不得绕过 eval/gate。

### 8.5 Focus / Mutate

保持 Poirot IVE 五问和 `FIX/CAPTURED` 类型。candidate 写 staging，不覆盖 active Skill。

### 8.6 Eval / Gate（G14/G15 resolved）

本 feature 不新增 workflow benchmark、replay corpus、offline fixture、live canary 或领域 benchmark hard gate。冻结 Poirot 父本没有这些机制；为遵守迁移式照抄，不自行补设计。

candidate 评价按冻结父本移植：

1. programmatic/static Skill contract checks；
2. `RegistryEvalBridge` 只调用 `ResponseContractChecker`；`SkillJudgmentAnalyzer` 与 `TaskQualityJudge` 按 Poirot 作为 post-execution metrics 独立运行，不进入本次 candidate promotion score；
3. EvalResult score/hard_failures/evidence/confidence/recommendation；
4. ScoreDeltaGate；
5. 版本记录和 attribution 完整。

Poirot `EvalContext.replay_samples` 在 v1 保持父本当前空值语义。不得把测试用例或 live workflow run 另行升级为生产 promotion gate。

`ScoreDeltaGate` 的 `min_delta` 由冻结父本源码确定为默认 `0.0`（G16 resolved）：FIX 必须满足 `candidate_score > baseline_score` 且无 hard failures；CAPTURED 无 baseline 时必须 `score > 0` 且无 hard failures。不自行提高阈值或增加新评分维度。

### 8.7 Activate / Rollback

- active pointer 切换语义复用 Poirot store；
- feature flags 默认关闭；显式启用 evolution/eval 后，ScoreDeltaGate accept 立即调用 `create_version()`，candidate 成为同名唯一 active，旧版停用；
- 不新增 shadow、pending approval 或二次 promotion gate；
- 新版本只影响新任务；
- GitRatchet 按冻结父本实际行为回滚：active 版本至少 5 次 selection 且 `effective_rate < 0.3` 时切回 parent；RuntimeTracker trend 仅用于 health/advice，不独立触发回滚；
- rollback 不删除候选和历史。

---

## 9. Poirot Eval 边界（G14/G15 resolved）

### 9.1 明确不建立 benchmark

- 不建立 baseline/candidate workflow replay；
- 不维护全局竞品题库或 gold answer；
- 不录制搜索工具响应作为 promotion corpus；
- 不要求 live web canary；
- 不按 plan/search/extraction/write 自行设计新的 benchmark score；
- 不扩展为与 Poirot 不同的 protocol pooling 体系。

### 9.2 评价来源

冻结 Poirot 父本的 promotion 只使用 `RegistryEvalBridge → ResponseContractChecker → ScoreDeltaGate`。`SkillJudgmentAnalyzer`、`TaskQualityJudge` 与 `RuntimeTracker` 保留为 post-execution/longitudinal metrics，其中 RuntimeTracker 数据供健康报告，GitRatchet 的实际回滚条件仍是 effective rate。必要改动仅限 LangChain→Pi、journal→JSONL/SOCM/span 和 store→app.db 适配。

### 9.3 行为验证与 promotion eval 分离

本 feature 的实现仍须按仓库交付规则运行 faux/live smoke verification，证明注入、进化、晋升和回滚路径工作；这些工程验证不成为生产 candidate 的 benchmark 数据或自动晋升输入。

---

## 10. 配置与默认关闭（resolved）

沿用 Poirot 配置语义和默认值，仅换本仓前缀并收敛到 App：

```text
WORKFLOW_SKILL_ENABLED=false
WORKFLOW_SKILL_EVOLVE_ENABLED=false
WORKFLOW_SKILL_EVAL_ENABLED=false
WORKFLOW_SKILL_MAX_INJECT=3
WORKFLOW_SKILL_QUALITY_THRESHOLD=0.3
WORKFLOW_SKILL_MIN_SELECTIONS=5
WORKFLOW_SKILL_EVOLVE_THRESHOLD=0.3
WORKFLOW_SKILL_EVOLVE_COOLDOWN_SELECTIONS=10
```

`WORKFLOW_SKILL_MAX_INJECT=3` 经 G6 冻结为每次、每 scope 的硬上限：只注入当前 scope 最相关的最多 3 个完整 Skill；不足不补位，不跨 scope 累加，不截断单个 Skill。沿用 Poirot，不追加 token/金额预算。

G26 由冻结父本决定：不新增 reflection/mutation/eval token、金额或每日调用预算；保留 Poirot 已有局部限制 `LLMMutator(max_changed_lines=20, max_steps=5)`、TaskQualityJudge `_MAX_TRACE_CHARS=80000` 和 `_MAX_OUTPUT_CHARS=20000`。其中父本未实际消费的 `max_steps` 不在 v1 自行扩展为新循环。

G27 由冻结父本范围决定：LLMMutator 只生成/修改单个 `SKILL.md`；CAPTURED 的 `allowed_tools=()`，FIX 保留 baseline frontmatter/allowed-tools。v1 不生成、引用、复制或执行 host script，不增加 executable artifact、approval 或 sandbox 机制。

G28 决定完全沿用 Poirot，不新增 prompt-injection 防护：不增加 sanitizer、untrusted-content 结构化隔离、恶意指令分类器、quarantine 或人工批准。WorkflowEvidenceAdapter 可做格式/长度适配，但不得以安全策略过滤原始内容。该选择明确接受网页、tool output 或 trace 中指令性文本可能影响 focuser/mutator/candidate 的父本风险，仍只依赖 Poirot 既有 prompts、ResponseContractChecker 与 ScoreDeltaGate。

G29 按 Poirot 处理：父本没有 report-feedback 特权通道，用户输入只作为 messages/journal/execution trace 的普通上下文。当前 `report_feedback` 可被 WorkflowEvidenceAdapter 纳入普通 evidence，由 IVEFocuser 判断；不得直接写 `fix_direction`/`capture_pattern`，不得跳过 G11 的已奏效解法条件、ResponseContractChecker 或 ScoreDeltaGate。

冻结默认：

- `WORKFLOW_SKILL_ENABLED=false`：Skill 模块 opt-in；
- `WORKFLOW_SKILL_EVOLVE_ENABLED=false`：evolution 独立 opt-in；
- `WORKFLOW_SKILL_EVAL_ENABLED=false`：L3 eval 独立 opt-in；false 时使用 ProgrammaticEvalBridge，true 时使用 RegistryEvalBridge；
- eval 子开关沿用 Poirot：judgment/task judge/contract check/async eval/skip-no-skill 默认 true；
- 不提供 shadow 模式；
- 显式启用 evolution/eval 后，Poirot gate accept 自动激活新版本。

**RESOLVED-P4：保留 Poirot 三个独立顶层开关及其默认 false。**

---

## 11. 许可证与来源追踪

1. Poirot 根许可证是 MIT，Copyright `(c) 2026 Poirot Authors`。
2. 所有 COPY/ADAPT 文件必须保留 MIT notice 和 upstream path/SHA。
3. Poirot 自带部分 builtin skills 来源于 hermes-agent/deer-flow；本 feature 不搬 builtin skills，因此初始范围不引入这些二级内容。
4. 若后续决定搬任一 builtin skill，必须同步复制其原始 author/license frontmatter 和 Poirot `THIRD_PARTY_LICENSES.md` 对应声明。
5. 实现计划必须包含 attribution gate，禁止“算法抄了但删来源”。

---

## 12. Grilling 决策记录（G1–G29 全部 resolved）

### 来源与移植

- **G1（resolved）**：Poirot 父本冻结为 `86bf279ad90c180f0ba696755620dd7d6661465e`；实现期不追 `master`；上游更新只能通过显式 source rebase。
- **G2（resolved）**：采用迁移式照抄；能直接搬则 COPY，架构要求下允许 ADAPT/REWRITE；以当前架构正确性优先。审计使用 module map、provenance 和 host-delta/rewrite rationale，不设文本相似度阈值，不强制永久保存逐文件 diff。
- **G3（resolved）**：目录服从本仓六边形分层；语义未变的 Poirot 模块叶子名、类名和核心方法名原样保留；host glue/语义变化对象按本仓职责命名。
- **G4（resolved）**：由现有 asyncio API 决定；LLM/DB/文件/workflow 边界改 async，纯计算保持同步；禁止阻塞事件循环。

### Skill 边界

- **G5（resolved）**：固定四类语义 scope：`plan/search/extraction/write`；extraction 不新增 stage，但独立注入、归因和评价。
- **G6（resolved）**：沿用 Poirot `max_inject=3`；每次、每 scope 最多注入 3 个完整 Skill；不足不补位、不跨 scope 累加、不截断。
- **G7（resolved）**：按 scope 延迟选择并固定；plan→search/extraction→write 逐步利用前序结果；首次绑定后任务内永久固定，resume 复用，运行中 promotion/rollback 不改绑定。
- **G8（resolved）**：不创建 Base `SKILL.md`；固定流程只由代码/profiles/SOCM/feature contract 表达；learned Skill 仅作为四类 overlay。

### Trigger 与 Capture

- **G9（resolved）**：只观察 `completed` 和 `failed`；`aborted` 完全忽略，不生成 observation、不计指标、不触发 mutation。
- **G10（resolved）**：已有 Skill 的 FIX 沿用 Poirot `min_selections=5 / evolve_threshold=0.3 / cooldown_selections=10` 和原 MetricMonitor 指标语义；CAPTURED 另由 G11 决定。
- **G11（resolved）**：v1 保留证据型 `CAPTURED`；必须同时有问题证据、轨迹中实际奏效的解法、可迁移性和去重结果；无解法只记 observation；candidate 未通过 Poirot eval/gate 不得激活。
- **G12（resolved）**：Poirot 冻结父本未实现 DERIVED，本 feature 不自行补设计；v1 不生成、不激活、不暴露 DERIVED。上游 Literal 若因 COPY 保留，仅作不可达兼容值。
- **G13（resolved）**：完全删除 manual capture；不保留内部方法，不新增 HTTP/CLI/UI；CAPTURED 仅由 post-task 自动闭环产生。

### Evaluation 与 Promotion

- **G14（resolved）**：Poirot 冻结父本没有 workflow benchmark，本 feature 不自行建立 benchmark/corpus/replay/live canary；promotion 只走父本 EvalBridge + ScoreDeltaGate。
- **G15（resolved / not applicable）**：不存在 offline fixture 与 live replay promotion gate；工程 smoke verification 不进入生产晋升数据。
- **G16（resolved，代码父本已决定）**：沿用 Poirot `min_delta=0.0`；FIX 严格高于 baseline，CAPTURED score>0，二者均要求无 hard failures。
- **G17（resolved）**：沿用 Poirot 自动激活；flags 默认关闭，显式启用后 gate accept 立即 `create_version()` 并切唯一 active；不做 shadow/人工批准。
- **G18（resolved）**：严格沿用 Poirot GitRatchet 实际行为：至少 5 次 selection 后 `effective_rate < 0.3` 回滚 parent；RuntimeTracker trend 仅 advisory；不加 workflow 指标。
- **G19（resolved，代码父本已决定）**：TaskQualityJudge 保留 0.50/0.35/0.05/0.10 权重，但只存 post-execution task score，不进入 RegistryEvalBridge 或 ScoreDeltaGate promotion 总分。

### 数据与生命周期

- **G20（resolved）**：Poirot 原表/字段照搬进现有 `app.db`；scope/bindings/observations 使用 companion tables；不改写上游 row mapper/CRUD 语义。
- **G21（resolved）**：保留 Poirot skill_id/sidecar/hash 规则；所有版本放 `learned_skills/skills/<skill-id>/`；App 原子维护 package.json `pi.skills`，只加载每个 name 当前唯一 active，candidate/history 不进入 manifest。
- **G22（resolved）**：删除 task 时删除原始 evidence、bindings 和 observations；保留 Skill versions/evolution/聚合 metrics/去标识 judgments，清空 task/run 引用；不因任务删除回滚已学 Skill。
- **G23（resolved）**：rejected candidate 在 EvolutionRecord 成功持久化后立即删完整文件，只保留 id/diff/score/reason；记录失败则保留文件并 fail closed；accepted versions 永久保留。
- **G24（resolved）**：单进程 global asyncio lock 串行全部 evolution cycle；锁内重新扫描 trigger/active pointer；v1 不支持共享存储的多进程 writer，不设计 per-skill CAS/分布式锁。
- **G25（resolved）**：完全沿用 Poirot，不恢复中断 cycle、不持久化步骤、不做启动对账/manifest 重建/orphan 清理；接受父本原有 crash window。

### 安全与成本

- **G26（resolved，代码父本已决定）**：不新增 token/金额/日预算；原样保留 max_changed_lines=20、max_steps=5、trace=80000 chars、output=20000 chars 等 Poirot 局部限制。
- **G27（resolved，代码父本已决定）**：只生成/修改 SKILL.md；CAPTURED allowed_tools=()，FIX 保留原值；不生成、引用或执行 host script。
- **G28（resolved）**：完全沿用 Poirot，不新增 sanitizer/结构化隔离/分类器/quarantine/人工批准；接受外部内容影响自进化 prompt 的父本风险。
- **G29（resolved，父本语义）**：用户 feedback 只作普通 execution evidence，由 IVEFocuser 判断；不作为特权 mutation instruction，不直接写 fix_direction/capture_pattern，不绕过 CAPTURED/eval/gate。

---

## 13. 冻结状态与实现完成

本文于 2026-07-30 冻结为 v0.2.0，并于建立计划时做无语义边界变化的文档一致性 patch v0.2.1；实现计划 v0.1.0 已完成，冻结门仍满足：

1. G1–G29 全部关闭；
2. COPY/ADAPT/REWRITE/OMIT/NEW-HOST module map 已锁定并完成 attribution audit；
3. upstream SHA 与 MIT attribution 已锁定并写入移植/改编文件头；
4. Skill 注入点和 task version snapshot 已端到端验证；
5. SQLite schema、SoT、删除和保留边界已验证；
6. Poirot eval、ScoreDeltaGate、promotion 和 runtime rollback 已验证；
7. 明确不建立生产 benchmark，工程实现已提供可观察 offline/faux/live smoke verification；
8. 本 feature 不修改架构契约 D*/G*；架构契约仍 v0.3.6；
9. Roadmap、feature、plan 状态已同步；
10. `packages/ai|agent` 无业务改动、无新 HTTP route、无第二 Agent runtime。

后续变更必须建立新的 feature/plan 或按现有冻结边界提交；不得从本 feature 推断未冻结 backlog。

---

## 14. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| `0.2.1` | 2026-07-30 | 建立并完成实现计划 [`P4_workflow_skill_self_evolution.md`](../plans/P4_workflow_skill_self_evolution.md) v0.1.0；校正 §6 文件树与 G21 一致为 `skills/<skill-id>/SKILL.md + .skill_id`；O1–O16、S1–S4、真实 provider L1–L2 全部通过；无行为边界变化，架构契约仍 v0.3.6 |
| `0.2.0` | 2026-07-30 | 用户确认最终冻结；G1–G29 决策、Poirot frozen SHA、transplant-first module map、FIX/CAPTURED、四 scope、数据/文件/晋升/回滚/删除/并发/预算/安全边界正式生效；架构契约保持 v0.3.6；尚未建立实现计划 |
| `0.2.0-draft` | 2026-07-30 | 完成 G1–G29 grilling：冻结 Poirot SHA；确立 transplant-first；四 scope、每 scope≤3、延迟选择固定版本；FIX/CAPTURED、无 DERIVED/manual capture；不新增 benchmark/prompt-injection 防护/crash recovery；保留 Poirot eval/promotion/rollback；原表+companion tables；全部版本放 capability skills 并由 manifest 只加载 active；删除 task 保留学习结果；rejected candidate 立即删除；全局串行 cycle；仍待最终冻结审阅 |
| `0.1.0-draft` | 2026-07-30 | 初始方案：确认 App-owned Workflow Skill Overlay；核心要求升级为 transplant-first，建立 Poirot L1/L2/L3 搬运 module map、最小 host glue、当前 Skill 注入缺口、eval/rollback 候选边界和 G1–G29 grilling 清单；grilling 已决定不自行建立 Poirot 父本不存在的 workflow benchmark；不改架构契约，禁止实现直到 frozen |
