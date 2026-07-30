# Plan: P4 — Workflow Skill Self-Evolution v1（Poirot transplant-first）

| Field | Value |
|-------|-------|
| **plan_id** | `P4-workflow-skill-self-evolution` |
| **plan_version** | `0.1.2` |
| **status** | **completed — implementation and verification green** |
| **created** | 2026-07-30 |
| **updated** | 2026-07-30 |
| **roadmap** | [`docs/ROADMAP.md`](../ROADMAP.md) stage **P4** `competitive_app` |
| **contract** | [`docs/contracts/ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.6** |
| **feature** | [`docs/features/workflow_skill_self_evolution_v1.md`](../features/workflow_skill_self_evolution_v1.md) **v0.2.1 frozen** — `workflow-skill-self-evolution-v1`（G1–G29） |
| **depends_on** | `research-workflow-v1` v0.2.3；P3 local capability loader；P3.1 extension runtime；现有 `data/app.db`/JSONL/SOCM |
| **upstream** | [`HezaoHezao/poirot`](https://github.com/HezaoHezao/poirot/tree/86bf279ad90c180f0ba696755620dd7d6661465e) frozen SHA `86bf279ad90c180f0ba696755620dd7d6661465e` |
| **target** | `competitive_app` + `capability_packages/learned_skills`；`packages/ai|agent` **零业务改动** |
| **tests** | `tests/competitive_app/{contract,unit,integration,integration/live}/` |
| **non_goal** | benchmark/replay；DERIVED；manual capture/API；host scripts；prompt-injection 防护；crash recovery；第二 Agent 内核；Pi core 业务 policy |

---

## 0. Purpose

1. 按冻结 feature v0.2.1，在现有六边形架构内迁移 Poirot Skill L1/L2/L3 自进化闭环。
2. 先修通 plan/search/extraction/write 四个 scope 的 Skill 选择、注入与 task-pinned version binding；这是 mutation/versioning 前的硬门。
3. 移植 Poirot Skill 类型、parser、store、selector、metrics、eval、EvolutionManager、FIX/CAPTURED、promotion 和 rollback；能 COPY 就 COPY，只有 host 边界冲突才 ADAPT/REWRITE。
4. 把业务观察、生命周期和文件投影留在 `competitive_app`；Skill 内容作为本地 capability snapshot 落 `capability_packages/learned_skills`。
5. 保持固定三阶段 workflow、SOCM、budget、termination、schema、工具白名单、JSONL SoT 和现有 HTTP surface 不变。
6. 用 observable behavior tests + faux/live smoke 证明链路工作；测试不成为生产 promotion benchmark。

**Approach:** transplant-first。冻结 Poirot SHA 是唯一代码父本；每个 COPY/ADAPT/REWRITE 文件记录 upstream path/SHA、MIT attribution 和 host delta。不得按“相似思想”另写第二套 evolution 算法。

---

## 1. Binding constraints

| ID | Must |
|----|------|
| Feature v0.2.1 | G1–G29 与 §1–§13 全部锁定；不得重新解释 |
| G1/G2/G3 | frozen SHA；transplant-first；本仓分层 + Poirot 符号名 |
| G4 | LLM/DB/FS/workflow 边界 async；纯计算同步；禁止阻塞事件循环 |
| G5–G8 | scope=`plan/search/extraction/write`；每 scope≤3；延迟选择后 task-pinned；无 Base SKILL.md |
| G9–G13 | 只观察 completed/failed；FIX=5/0.3/10；证据型 CAPTURED；无 DERIVED/manual capture |
| G14–G19 | 不建 benchmark；Poirot EvalBridge/ScoreDeltaGate；accept 自动 active；effective_rate<0.3 回滚 |
| G20–G25 | Poirot 原表 + companion tables；所有版本在 capability skills；删除/retention/串行/no-recovery 语义锁定 |
| G26–G29 | 无新增 token budget/script/security gate；feedback 只作普通 evidence |
| D8/D9 | 业务 policy 只进 `competitive_app`；固定 workflow 状态机不变 |
| D22 | 本地 capability package only；无 install/npm/git/remote Skill |
| D24/D25 | transcript/tool SoT=JSONL；SOCM=evidence/coverage SoT；SQLite 只存索引/投影/Skill operational state |
| Layering | `domain/evolution` 无 FastAPI/aiosqlite/pi_agent/pi_ai/FS import |
| Public API | 不新增/删除/改义 HTTP route；不引入 CLI/UI/manual capture |
| Pi boundary | 不修改 `packages/ai|agent` 公共 API，不把 app.db 反向泄漏给 Pi loader |
| License | 每个直接复制/实质改编文件保留 Poirot MIT、upstream path 和 frozen SHA |

### G0 prerequisite

实现开始前记录基线：

```bash
.venv/bin/pytest tests/competitive_app tests/packages/agent tests/capability_loader -m "not live" -q
```

若已有失败，先记录为基线；不得通过缩小本 feature 或改 Pi core 规避。

---

## 2. Frozen source module map

### 2.1 Layer 1 — Skill foundation

| Mode | Poirot source @ frozen SHA | Target | Host delta / parity obligation |
|------|-----------------------------|--------|--------------------------------|
| ADAPT | `agents/skill/config.py` | `application/evolution/config.py` | env 前缀改 `WORKFLOW_SKILL_*`；db/dirs 接 AppConfig；默认值原样 |
| COPY | `agents/skill/types.py` | `domain/evolution/skill_types.py` | import path；scope 放 companion metadata，不破坏上游 value object |
| ADAPT | `agents/skill/store.py` | `adapter/out/persistence/learned_skill_store.py` | SQLite 连接接现有 app.db/async lock；原表/字段/CRUD/active pointer 语义不变 |
| COPY+ADAPT | `agents/skill/parser.py` | `application/evolution/parser.py` | root 改 learned_skills；保留 `.skill_id`/ID/hash/frontmatter 语义 |
| ADAPT | `agents/skill/injector.py` | `application/evolution/injector.py` | LangChain SystemMessage → Pi `skill_to_context_injection`/system prompt composition |
| ADAPT | `agents/skill/selector.py` | `application/evolution/selector.py` | LLM→Pi async；按 scope 延迟选择；最多 3；选后 task-pinned |
| ADAPT | `middlewares/skill_injection_middleware.py` | `application/evolution/stage_skill_composer.py` | 去 AgentMiddleware；接 ResearchRunner/CoverageEngine/extraction prompt |
| ADAPT | `middlewares/skill_metrics_middleware.py` | `application/evolution/skill_metrics.py` | 去 AgentMiddleware；selection/outcome 接 task terminal + Pi extension provenance |
| OMIT | `agents/skill/builtin_skills/**` | — | 不搬 36 builtin skills |
| OMIT | `agents/skill/hub/**` | — | 不搬 hub/quarantine/install |

### 2.2 Layer 2 — Evolution

| Mode | Poirot source @ frozen SHA | Target | Host delta / parity obligation |
|------|-----------------------------|--------|--------------------------------|
| COPY | `agents/skill/evolution/types.py` | `domain/evolution/evolution_types.py` | import path；DERIVED Literal 若保留必须不可达 |
| COPY | `agents/skill/evolution/protocols.py` | `application/evolution/protocols.py` | import path；IO-facing implementation async 化时保持职责 |
| ADAPT | `agents/skill/evolution/manager.py` | `application/evolution/evolution_manager.py` | async；删除 manual `capture_skill()`；编排次序不变 |
| COPY+ADAPT | `evolution/triggers/metric_monitor.py` | `application/evolution/triggers/metric_monitor.py` | store async；5/0.3/10、anti-loop 原样 |
| OMIT | `evolution/triggers/capture_trigger.py` | — | manual capture 被 G13 删除 |
| ADAPT | `evolution/focus/ive_focuser.py` | `application/evolution/focus/ive_focuser.py` | PiLlmAdapter；JSONL/SOCM/span/feedback evidence |
| ADAPT | `evolution/mutators/llm_mutator.py` | `application/evolution/mutators/llm_mutator.py` | Pi async LLM；root/manifest 适配；20 lines/5 steps/frontmatter/diff 语义保留 |
| COPY | `evolution/gates/score_delta_gate.py` | `application/evolution/gates/score_delta_gate.py` | `min_delta=0`、CAPTURED score>0、hard failure reject 原样 |
| COPY+ADAPT | `evolution/gates/git_ratchet.py` | `application/evolution/gates/git_ratchet.py` | async store；5 selections/effective_rate<0.3/parent rollback 原样 |
| COPY | `evolution/eval/programmatic_bridge.py` | `application/evolution/eval/programmatic_bridge.py` | import path；facade 保留 |

### 2.3 Layer 3 — Eval

| Mode | Poirot source @ frozen SHA | Target | Host delta / parity obligation |
|------|-----------------------------|--------|--------------------------------|
| COPY | `agents/skill/eval/types.py` | `domain/evolution/eval_types.py` | 不增加 benchmark identity |
| COPY+ADAPT | `agents/skill/eval/registry.py` | `application/evolution/eval/registry.py` | async FS adapter；instance registry/fail-closed 原样 |
| COPY | `eval/analyzers/protocols.py` | `application/evolution/eval/analyzers/protocols.py` | import path |
| COPY | `eval/analyzers/checks.py` | `application/evolution/eval/analyzers/checks.py` | 静态规则原样 |
| COPY | `eval/analyzers/contract_compiler.py` | `application/evolution/eval/analyzers/contract_compiler.py` | 规则编译原样 |
| COPY+ADAPT | `eval/analyzers/response_contract_checker.py` | `application/evolution/eval/analyzers/response_contract_checker.py` | import/async FS 适配；不加 workflow hard gate |
| ADAPT | `eval/analyzers/skill_judgment_analyzer.py` | `application/evolution/eval/analyzers/skill_judgment_analyzer.py` | LangChain→Pi；messages/journal→JSONL/SOCM/span |
| ADAPT | `eval/analyzers/task_quality_judge.py` | `application/evolution/eval/analyzers/task_quality_judge.py` | LangChain→Pi；0.50/0.35/0.05/0.10 与 char caps 原样；不进 promotion |
| COPY+ADAPT | `agents/skill/eval/runtime_tracker.py` | `application/evolution/eval/runtime_tracker.py` | async store；window=20/delta=0.15/advisory 原样 |

### 2.4 Host-only files

| Mode | Target | Responsibility | Forbidden |
|------|--------|----------------|-----------|
| NEW-HOST | `domain/evolution/workflow_scope.py` | 四 scope、problem signature/evidence ref 的纯值对象 | IO/LLM/DB |
| NEW-HOST | `application/evolution/adapters/pi_llm.py` | Poirot `invoke` 语义→`pi_ai.completeSimple` async | 新模型框架 |
| NEW-HOST | `application/evolution/adapters/workflow_evidence.py` | JSONL/SOCM/span/feedback→FailureEvidence/ordinary context | sanitizer/quarantine/benchmark |
| NEW-HOST | `application/evolution/skill_version_snapshot.py` | per-scope first-bind + resume reuse | 运行中重选 |
| NEW-HOST | `application/evolution/post_task_observer.py` | completed/failed observation + CAPTURED eligibility；忽略 aborted | manual capture/DERIVED |
| NEW-HOST | `application/evolution/cycle_runner.py` | global asyncio lock；锁内重扫；调 EvolutionManager | per-skill CAS/distributed lock/recovery job |
| NEW-HOST | `application/evolution/skill_files.py` | `<skill-id>/SKILL.md`、manifest active list、reject delete | GC/crash reconciliation |
| NEW-HOST | `adapter/out/persistence/workflow_skill_store.py` | scope/binding/observation companion tables | 改 Poirot 原表字段 |

### 2.5 Explicit omissions

- LangGraph/LangChain Agent runtime、AgentMiddleware 外壳、LeaderAgent。
- Poirot reflection sufficiency middleware、memory、sandbox、MCP、multi-agent、Hub、TUI、CLI。
- DERIVED trigger/generator/eval；manual capture method/route。
- Workflow benchmark、replay corpus、gold answer、live promotion canary。
- Prompt-injection sanitizer、classification、quarantine、human approval。
- Evolution job table、crash resume、startup reconciliation/orphan cleanup。
- Host scripts/executable generated artifacts。

---

## 3. Target layout

```text
competitive_app/src/competitive_app/
  domain/evolution/
    __init__.py
    skill_types.py
    evolution_types.py
    eval_types.py
    workflow_scope.py

  application/evolution/
    __init__.py
    config.py
    parser.py
    injector.py
    selector.py
    stage_skill_composer.py
    skill_metrics.py
    skill_version_snapshot.py
    post_task_observer.py
    cycle_runner.py
    skill_files.py
    protocols.py
    evolution_manager.py
    adapters/
      __init__.py
      pi_llm.py
      workflow_evidence.py
    triggers/
      __init__.py
      metric_monitor.py
    focus/
      __init__.py
      ive_focuser.py
    mutators/
      __init__.py
      llm_mutator.py
    gates/
      __init__.py
      score_delta_gate.py
      git_ratchet.py
    eval/
      __init__.py
      programmatic_bridge.py
      registry.py
      runtime_tracker.py
      analyzers/
        __init__.py
        protocols.py
        checks.py
        contract_compiler.py
        response_contract_checker.py
        skill_judgment_analyzer.py
        task_quality_judge.py

  adapter/out/persistence/
    learned_skill_store.py
    workflow_skill_store.py

  application/workflow/
    research_runner.py          # modify: plan/write selection + injection + terminal observation
    coverage_engine.py          # modify: search/extraction injection
    task_service.py             # modify: resume binding reuse + delete semantics

  adapter/out/persistence/
    task_projection_store.py    # modify: schema/bootstrap + delete cleanup coordination

  wiring.py                     # modify: config/store/selector/evolution lifecycle

capability_packages/learned_skills/
  package.json                  # pi.skills lists active files only
  skills/
    <skill-id>/
      SKILL.md
      .skill_id

config/settings.example.yaml    # workflow_skill section, default disabled

tests/competitive_app/
  contract/test_workflow_skill_evolution_contract.py
  unit/evolution/
  integration/test_workflow_skill_injection.py
  integration/test_workflow_skill_evolution.py
  integration/live/test_live_workflow_skill_evolution.py
```

`packages/ai|agent` 不新增/修改文件。

---

## 4. Status board

Status: `todo` | `in_progress` | `done` | `blocked`。

| Step | Phase | Status | Contract mapping |
|------|-------|--------|------------------|
| G0 | Baseline suites + frozen SHA/provenance gate | done | G1–G4 |
| A1 | Capability package + config scaffold | done | G20/G21/G26 |
| A2 | Domain value objects + protocols | done | G3–G5/G12 |
| A3 | Poirot parser + ID/hash/frontmatter parity | done | G21 |
| A4 | Poirot tables/CRUD in app.db + companion tables | done | G20 |
| A5 | Store/parser parity tests | done | O1–O4 |
| B1 | Selector + injector + StageSkillComposer | done | G5–G8 |
| B2 | Task-pinned scope bindings + resume | done | G7 |
| B3 | ResearchRunner plan/write injection | done | feature §5.1 |
| B4 | CoverageEngine search/extraction injection | done | feature §5.2 |
| B5 | Selection/outcome/provenance metrics | done | G9/G10/G18 |
| B6 | First implementation gate: four scopes proven | done | O5–O8 |
| C1 | Programmatic checks/compiler/checker | done | G14–G16 |
| C2 | ProgrammaticEvalBridge + RegistryEvalBridge | done | G14–G19 |
| C3 | SkillJudgment + TaskQuality + RuntimeTracker | done | G18/G19/G26 |
| C4 | PiLlmAdapter | done | G4 |
| D1 | MetricMonitor + IVEFocuser | done | G10/G29 |
| D2 | LLMMutator FIX/CAPTURED | done | G11/G12/G13/G26–G28 |
| D3 | ScoreDeltaGate + GitRatchet | done | G16–G18 |
| D4 | Async EvolutionManager + global cycle lock | done | G4/G24/G25 |
| D5 | PostTaskObserver + evidence adapter | done | G9/G11/G28/G29 |
| E1 | Candidate/version files + active manifest | done | G17/G21/G23 |
| E2 | Promotion/reject/rollback lifecycle | done | G16–G18/G23 |
| E3 | Task deletion cleanup/retention | done | G22 |
| E4 | Wiring + three opt-in flags | done | feature §10 |
| F1 | Contract/unit tests O1–O6 | done | layering/parity |
| F2 | Integration tests O7–O16 | done | end-to-end behavior |
| F3 | Faux smoke S1–S4 | done | delivery verification |
| F4 | Live smoke L1–L4 | done | delivery verification only |
| F5 | Attribution audit + docs/roadmap completion sync | done | G1/G2/license |

**Hard ordering:** A → B → C → D → E → F。B6 必须通过后才能开始 C/D；这是 feature §5.3 的第一实现门。

---

## 5. Phased implementation

### Phase A — Port foundation and persistence

**A1. Capability/config scaffold**

- 建 `capability_packages/learned_skills/package.json`，初始 `pi.skills=[]`；不建 builtin Skill。
- 移植 `SkillConfig`/`SkillEvalConfig`，env 前缀改 `WORKFLOW_SKILL_*`；默认三顶层开关 false。
- `config/settings.example.yaml` 只记录 App enablement/root；provider secrets 仍走 env。

**A2. Value objects and protocols**

- COPY Poirot Skill/evolution/eval frozen dataclasses 和 Literals。
- `DERIVED` 若因 COPY 存在，只允许 parser/store round-trip，不得有 trigger/manager public path。
- NEW-HOST `SkillScope`、evidence refs 保持 pure domain。

**A3. Parser/files**

- 保留 name regex、frontmatter、allowed-tools、enabled、`.skill_id`、UUID8、content hash16。
- FIX 不改 name/allowed-tools；CAPTURED allowed_tools=()。
- 所有 candidate/history/active 路径为 `skills/<skill-id>/SKILL.md`。

**A4. Store**

- 将 Poirot schema/CRUD 移植进现有 App SQLite bootstrap；不另建 DB。
- 原表保持字段和 row mapper；连接/事务改现有 async connection + write lock。
- companion tables：`workflow_skill_metadata`、`skill_task_bindings`、`skill_observations`。
- 不把 transcript/SOCM 正文复制进 SQLite。

**Exit A:** O1–O4 通过；parser/store parity 可独立运行；无 workflow 接入。

### Phase B — Skill selection and four-scope injection

**B1. Selector/injector**

- ADAPT Poirot selector 的 quality filter/LLM selection；只从 DB active+enabled 集合选。
- 每 scope 最大 3；不足不补；Skill 内容完整注入，不截断。
- `StageSkillComposer` 用 Pi Skill injection 构造 scope-specific system prompt。

**B2. Binding**

- plan 首入选择 plan；search 首入选择 search+extraction；write 首入选择 write。
- 选择后原子写 `skill_task_bindings`；resume 有 binding 就复用，无 binding 才首次选择。
- promotion/rollback 不改变现有 task bindings。

**B3. Main agent**

- `ResearchRunner._build_prompt()` 不再用裸 `profile.system_prompt` 覆盖 Skill；组合 base+selected。
- plan/write 未选 Skill 时行为与当前一致。

**B4. Search/extraction**

- `_HarnessFactory.build_ephemeral()`/CoverageEngine 接收已绑定 search Skills。
- 每个 search sub-agent 使用相同 pinned search versions。
- judge/extraction prompt 只注入 extraction scope，不新增 workflow stage。

**B5. Metrics/provenance**

- selection 在首次绑定时计；applied/completion/fallback 保持 Poirot 定义。
- completed/failed 写 outcome；aborted 完全不写 observation/outcome。

**Exit B / hard gate:** O5–O8 + S1 通过；四 scope 都能注入；未选 Skill 不出现；resume 固定版本。未通过不得开始 mutation/eval。

### Phase C — Poirot Eval L2/L3

**C1. Static evaluator**

- COPY checks/ContractCompiler；ADAPT ResponseContractChecker 只做 host FS/import。
- 不增加 workflow hard gate、gold answer 或 replay sample。

**C2. Bridges**

- eval disabled → ProgrammaticEvalBridge。
- eval enabled → instance-level RegistryEvalBridge；registry 空/异常 fail closed。
- ScoreDeltaGate `min_delta=0.0`。

**C3. Longitudinal metrics**

- SkillJudgmentAnalyzer、TaskQualityJudge post-execution async；异常 graceful degradation。
- TaskQuality 权重与 caps 原样；不进入 promotion score。
- RuntimeTracker window=20/delta=.15；trend 只 health/advice。

**C4. LLM adapter**

- 使用现有 App model/judge model + `pi_ai.completeSimple`；不引新 provider/router/framework。
- 不增加 token/金额/每日预算。

**Exit C:** O9–O11 通过；静态 gate 与 post-task metrics 的职责分离可观察。

### Phase D — Evolution and automatic capture

**D1. Trigger/focus**

- MetricMonitor 使用 5/0.3/10，anti-loop/cooldown 保留。
- WorkflowEvidenceAdapter 读取 JSONL/SOCM/span/feedback；不 sanitizer、不 quarantine。
- feedback 是普通 evidence，不直接写 mutation instruction。

**D2. Mutator**

- FIX/CAPTURED only；manual capture/DERIVED 分支不可达。
- 保留 max_changed_lines=20、max_steps=5、single-section、frontmatter、unified diff。
- 不生成 script/executable。

**D3. Gate/ratchet**

- hard failure reject；FIX score 严格高 baseline；CAPTURED score>0。
- GitRatchet 只按 min selections=5 + effective_rate<.3 回 parent。

**D4. Manager/cycle**

- `focus→mutate→eval→gate→create_version→record` 顺序不变。
- 去掉 manual `capture_skill()`；保留自动 CAPTURED context。
- global `asyncio.Lock` 串行全部 cycle；锁内重扫；无 distributed/CAS/job recovery。

**D5. PostTaskObserver**

- completed/failed 触发；aborted return。
- CAPTURED 同时要求问题 evidence、轨迹中实际奏效解法、transferability 和 dedupe。
- 只有问题无解法 → observation only。

**Exit D:** O12–O14 + S2/S3 通过；FIX/CAPTURED 都走同一 manager/eval/gate。

### Phase E — Activation, files, deletion, wiring

**E1. File/manifest lifecycle**

- App 原子重写 package.json `pi.skills`，只列每个 name 唯一 active path。
- candidate/history 文件保留在 `skills/`，但不进 manifest。
- 同一临界区先文件+DB active pointer，再 manifest；普通失败 fail closed。
- 按 G25 不实现 crash recovery/startup reconciliation。

**E2. Reject/rollback**

- reject：EvolutionRecord 成功后立即删 candidate `SKILL.md`/`.skill_id`/空目录；记录失败则保留文件。
- accept：版本永久保留并切 active；仅新任务使用。
- rollback：切 parent active + manifest；不删历史。

**E3. Task deletion**

- 现有 task/session/SOCM/spans/feedback 继续删除。
- 新增 bindings、未消费 observations、raw evidence refs 删除。
- Skill versions/evolution/aggregate metrics/de-identified judgments 保留；task/run refs 置空。

**E4. Wiring**

- AppState 持 config、stores、selector、observer、manager、cycle lock；shutdown 不恢复中断 cycle。
- 三顶层 flag 独立 opt-in；disabled 时当前 workflow 行为和 prompt 保持一致。
- 不新增 HTTP route。

**Exit E:** O15/O16 + S4 通过；重启只按正常 bootstrap 读已持久状态，不做对账。

### Phase F — Verification and closeout

- 只测试可观察行为、边界和真实失败；不测试源码文本相似度。
- 运行 targeted offline、全 app regression、faux smoke、env-gated live smoke。
- live smoke 不写入 production promotion corpus，不宣称 Skill 质量 benchmark。
- 完成 attribution audit：每个 COPY/ADAPT/REWRITE 文件的来源头、MIT、SHA、host delta。
- smoke 通过后才同步 plan `completed`、Roadmap 和 feature plan link；不改架构契约。

---

## 6. Verification matrix

### 6.1 Offline contract/unit/integration（exit-blocking）

| ID | Observable contract |
|----|---------------------|
| O1 | `domain/evolution` import scan 无 FastAPI/aiosqlite/pi_agent/pi_ai/FS；`packages/ai|agent` 无业务改动 |
| O2 | Poirot dataclasses/Literals/parser 对同 fixture 产相同 ID/hash/frontmatter/lineage；DERIVED public path 不存在 |
| O3 | app.db 含 Poirot 原表 + companion tables；register/get/get_active/create_version/rollback/metrics/eval CRUD 行为正确 |
| O4 | `WORKFLOW_SKILL_*` 非法 int/float 回默认；三顶层开关默认 false；disabled 时现有 workflow prompt/结果无变化 |
| O5 | plan 只注入绑定的 plan Skills；write 只注入 write；未选择 Skill 不出现；每 scope≤3 |
| O6 | search 每个 ephemeral sub-agent 收到相同 pinned search Skills；extraction judge 只收到 extraction Skills |
| O7 | plan→search/extraction→write 延迟选择；bindings 持久；resume 不重选；promotion 后在途 task 不变 |
| O8 | selection/applied/completion/fallback 与 completed/failed 正确计数；aborted 零 observation/零 outcome |
| O9 | ProgrammaticEvalBridge/RegistryEvalBridge 选择随 flag；registry/checker 异常 score=0 + hard failure + reject |
| O10 | ScoreDeltaGate：FIX strict delta>0；CAPTURED score>0；hard failures reject；无 workflow score |
| O11 | TaskQualityJudge 权重/caps/存储正确且不改变 promotion；RuntimeTracker trend 不独立触发 rollback |
| O12 | MetricMonitor 5/0.3/10 + cooldown；锁等待后重扫 active/metrics；同时触发仍全局串行 |
| O13 | FIX 保留 name/tools/frontmatter；CAPTURED allowed_tools=()；无 manual capture/DERIVED/script 路径 |
| O14 | CAPTURED 缺任一 problem/solution/transferability/dedupe 条件只记 observation；满足时走完整 gate |
| O15 | accept 切唯一 active + manifest 只列 active；reject 记录成功后删文件；记录失败保留；rollback parent |
| O16 | delete task 清 raw evidence/bindings/observations，保留 learned versions/evolution/aggregate/de-identified score |

### 6.2 Faux smoke（exit-blocking）

| ID | Scenario |
|----|----------|
| S1 | 运行 faux 三阶段 task；捕获四个注入点；断言 scope 隔离、≤3、未选不注入 |
| S2 | 构造已有 Skill 5 次低 effective outcomes；跑 cycle；产生 FIX candidate→gate accept→新任务使用新版本 |
| S3 | 构造 completed task 的问题+奏效解法；自动 CAPTURED；无 manual API；gate reject/accept 两路径可观察 |
| S4 | 新 active 累积 5 次且 effective_rate<.3；自动 rollback parent；已绑定旧 task 不变；新 task 用 parent |

### 6.3 Live smoke（env-gated，feature closeout 要求实际执行）

| ID | Scenario |
|----|----------|
| L1 | 真 provider + search capability 跑 completed task；plan/search/extraction/write 四个 active Skill 实际绑定（每 scope≤3），search Skill 记录 judgment/outcome；报告非空 |
| L2 | 真 provider 直接运行一次 FIX mutation；candidate 可解析，EvalResult 与 gate accept/reject 可观察 |
| L3 | 真 provider 通过 HTTP feedback→refine 完成 evidence-backed CAPTURED；PostTaskObserver→EvolutionCycleRunner→Eval/Gate→EvolutionRecord 全链路可观察 |
| L4 | 真 provider completed task 自动触发 FIX cycle；随后 degraded active version 经同一 cycle 的 GitRatchet 回滚 parent，manifest 同步 |

### 6.4 Commands

```bash
# Targeted evolution tests
.venv/bin/pytest tests/competitive_app/unit/evolution tests/competitive_app/integration/test_workflow_skill_injection.py tests/competitive_app/integration/test_workflow_skill_evolution.py -q

# App regression / contract
.venv/bin/pytest tests/competitive_app -m "not live" -q

# Pi/capability boundary regression
.venv/bin/pytest tests/packages/agent tests/capability_loader -m "not live" -q

# Live smoke
.venv/bin/pytest tests/competitive_app/integration/live/test_live_workflow_skill_evolution.py -m live -q
```

---

## 7. Risk register（accepted contract risks, not scope to fix）

| Risk | Contract handling |
|------|-------------------|
| External prompt injection enters evolution trace | G28 accepts Poirot risk；不加 sanitizer/quarantine |
| ScoreDeltaGate has no workflow benchmark | G14/G16；only Poirot checker/delta；不得补 benchmark |
| CAPTURED score>0 may auto-activate weak Skill | G16/G17；runtime effective-rate rollback is only online backstop |
| RuntimeTracker trend does not independently rollback | G18；保留 frozen source actual behavior |
| LLMMutator partial line budget may yield awkward content | 保留 Poirot behavior；ResponseContractChecker fail closed |
| Crash between DB/file/manifest steps | G25 accepts no recovery/reconciliation |
| Rejected candidate full content deleted | G23；EvolutionRecord diff/score/reason is retained |
| All versions reside under `skills/` | G21；package manifest must enumerate active only |
| Single-process writer limitation | G24；do not deploy multiple writers on same app.db/root |
| No token/cost budget | G26；only upstream local caps remain |

---

## 8. Definition of Done

- [x] §4 board G0–F5 全部 `done`
- [x] O1–O16 全绿
- [x] S1–S4 实际 smoke 通过
- [x] L1–L4 使用真实 provider 实际执行并保存可审计结果；不称 benchmark
- [x] 四 scope 注入 + task-pinned resume 行为端到端可观察
- [x] FIX 和证据型 CAPTURED 经 Poirot eval/gate 自动 accept/reject
- [x] GitRatchet effective-rate rollback 端到端可观察
- [x] app.db 原表/companion tables、manifest active-only、删除/retention 行为符合 feature
- [x] feature flags disabled 时现有 workflow 无行为回归
- [x] `packages/ai|agent` 无业务改动、无第二 Agent runtime、无新 HTTP route
- [x] 无 benchmark/DERIVED/manual capture/host script/security gate/crash recovery 偷渡
- [x] 所有 COPY/ADAPT/REWRITE 文件有 upstream SHA/path/MIT/host delta
- [x] Feature/plan/README/Roadmap 状态同步；架构契约仍 v0.3.6

---

## 9. Revision history

| Version | Date | Note |
|---------|------|------|
| `0.1.0` | 2026-07-30 | 建立实施计划：按 frozen feature v0.2.1 把 Poirot transplant-first 拆为 foundation→四 scope 注入硬门→eval→evolution→lifecycle→verification；逐文件 module map、O1–O16、S1–S4、L1–L2；implementation not started |

| `0.1.1` | 2026-07-30 | 完成 P4 Workflow Skill Self-Evolution：G0–F5、O1–O16、S1–S4；env-gated L1/L2 真实 provider smoke 通过；selector/judgment identifier normalization 与生命周期回滚/删除 retention 验证；架构契约保持 v0.3.6 |
| `0.1.2` | 2026-07-30 | 补齐此前未由 live 保证的 runtime 链路：TaskService refine→PostTaskObserver→CAPTURED manager、completed task→automatic FIX cycle、real-provider four-scope bindings，以及同一 cycle 的 GitRatchet rollback；L1–L4 全部通过；架构契约保持 v0.3.6 |