# CompetitorLens 实现路线图（Roadmap）

| 字段 | 值 |
|------|-----|
| **roadmap_version** | `0.1.31` |
| **status** | active |
| **updated** | 2026-07-30 |
| **架构契约** | [`docs/contracts/ARCHITECTURE_CONTRACT.md`](contracts/ARCHITECTURE_CONTRACT.md) **v0.3.6** |
| **目的** | 排期与完成门禁；**防止实现顺序/范围漂移** |

---

## 0. 怎么用这份文档

1. **架构冲突 → 先改契约 + ADR**，再改 roadmap。  
2. **范围冲突 → 改本文**，升 `roadmap_version`。  
3. 实现 PR 须标明：**阶段 ID（P1–P4，含 P3.1/P3.2）** + 对照上游（若移植）。
4. **禁止**在 P1–P3 未完成时合并依赖真基座的 `competitive_app` 主路径（契约 D16/G8）。

### 还要不要继续聊？

| 话题 | 状态 | 建议 |
|------|------|------|
| **包组织 / 路径 / import / 进程 / 技术栈** | **已冻结**（契约 **v0.3.5**） | **不必再聊**；要改走 ADR |
| **实现顺序与完成标准** | 见本文阶段 | 按 roadmap 执行；细节可在阶段开工时补 checklist |
| **业务能力（研究流程、报告等）** | 搜索 capability v1 **frozen** | 边界：[`docs/features/search_capability_packages_v1.md`](features/search_capability_packages_v1.md) **v0.1.12**；其余 workflow/报告另开 |
| **agent engine extensions** | **done** | feature **v0.3.0**（P3.1 completed baseline + P3.2 delta）；计划 **v0.2.4 completed** |
| **P3.2 Pi extension capability enablement** | **done** | feature **v0.1.0 frozen**；extension runtime delta **v0.3.0 frozen**；plan [`P3_2_pi_extension_capability_enablement.md`](plans/P3_2_pi_extension_capability_enablement.md) **v0.1.2 completed**；ADR 0009 |
| **capability 里具体有哪些搜抓包** | **frozen** + 实现计划 | 搜索 feature 契约；计划 [`docs/plans/P4_search_capability_packages.md`](plans/P4_search_capability_packages.md) |
| **workflow Skill 自进化** | **implemented / verified** | feature **frozen v0.2.1**；plan [`P4_workflow_skill_self_evolution.md`](plans/P4_workflow_skill_self_evolution.md) **v0.1.2 completed**；O1–O16、S1–S4、真实 provider L1–L4 green |

---

## 1. 总顺序（不可跳）

```text
P1  packages/ai          全量同构 main
        ↓
P2  packages/agent       C 档同构 main
        ↓
P3  capability 本地加载器 + capability_packages/ 约定
        ↓
P3.1 agent engine extension 运行时（S-engine 同构）
        ↓
P3.2 Pi extension capability enablement（generic bridge + upstream cache parity）
        ↓
P4  competitive_app      DDD + FastAPI + workflow（业务能力在此阶段引入）
```

| 阶段 | 仓库路径 | import | 完成前禁止 |
|------|----------|--------|------------|
| **P1** | `packages/ai/` | `earendil_works.pi_ai` | 宣称 agent 完成；写 competitive 主路径 |
| **P2** | `packages/agent/` | `earendil_works.pi_agent` | 宣称 loader/app 可依赖未完成 agent |
| **P3** | loader + `capability_packages/` | （loader 挂在 agent 扩展点或薄模块） | 远程 install；家目录发现 |
| **P3.1** | `pi_agent/extensions/` + loop emit | `earendil_works.pi_agent.extensions` | 宣称 extension 钩子完成；TUI/install |
| **P3.2** | `packages/ai` + `packages/agent` + local consumer package | `earendil_works.pi_ai` / `pi_agent.extensions` | Reasonix policy 写入 core；新 hook / TUI / 第二 runtime |
| **P4** | `competitive_app/` | `competitive_app` | 绕过 agent 直连厂商 SDK 当内核 |

**上游对照：** 一律 `https://github.com/earendil-works/pi` 的 **`main`**。

---

## 2. 阶段详解

### P1 — `packages/ai`（全量）

| 项 | 内容 |
|----|------|
| **目标** | main `packages/ai` **整包** TS→Python 同构移植（契约 D15） |
| **规范源** | `packages/ai/**` on main |
| **技术** | asyncio、与上游模块边界一致；Pydantic 用于需校验处（与 agent tool 衔接在 P2） |
| **完成标准（必须全部满足）** | ① 目录/模块职责可映射 upstream；② 公开 stream/model/usage 等行为可对照 main；③ `tests/packages/ai/` 有行为/回归测试（含 faux/录制策略任选，但要可重复）；④ 无 LangChain 等第二框架 |
| **显式不做** | competitive 业务；capability 搜抓实现 |
| **退出条件** | 阶段评审：对照 main 抽查 N 个 provider/入口 + 测试绿 → 标 `P1=done` |

### P2 — `packages/agent`（C 档）

| 项 | 内容 |
|----|------|
| **目标** | main `packages/agent` core+harness 目标面同构（契约 D3） |
| **依赖** | **P1 done** |
| **实现计划** | [`docs/plans/P2_packages_agent.md`](plans/P2_packages_agent.md) |
| **必含能力族** | loop/agent/tools/events/abort；session 树；**JSONL @ `data/sessions/`**；compaction/branch；skills/prompt 资源语义；steering/follow-up 等 main 已有控制面 |
| **完成标准** | ① 依赖 `earendil_works.pi_ai` 真包而非永久假实现；② JSONL session 可恢复；③ tool 校验时机对齐 TypeBox→Pydantic 语义；④ `tests/packages/agent/` 覆盖 loop+tool+session 主路径；⑤ 无竞品 domain 类型泄漏 |
| **显式不做** | 六阶段研究 DAG；远程 package-manager |
| **退出条件** | 用本地假 tool 跑通 prompt→tool→session 落盘→resume 冒烟 → `P2=done` |

### P3 — 本地 capability 加载

| 项 | 内容 |
|----|------|
| **目标** | **同构移植** coding-agent package-manager **本地子集**：发现/解析/加载 `capability_packages/` → 注册 tools（D5/D22 + ADR 0006） |
| **依赖** | **P2 done** |
| **实现计划** | [`docs/plans/P3_capability_loader.md`](plans/P3_capability_loader.md) **v0.2**（approach A） |
| **必含** | 列举子目录；导入约定入口；注册 `AgentTool`；加载失败可观测 |
| **可选** | skills/prompts 资源文件；启用白名单；gateway live |
| **显式不做** | npm/git 下载、`~/.pi` 扫描、`pi install` CLI、全文 coding package-manager |
| **完成标准** | ① 至少一个示例包（可 no-op/echo tool）可被 agent 调用；② 非法包失败不拖垮进程（策略明确）；③ 测试覆盖加载与注册 |
| **退出条件** | 文档化子包目录约定 + C1 faux 冒烟绿 → `P3=done` |

### P3.1 — Agent engine extension 运行时

| 项 | 内容 |
|----|------|
| **目标** | 同构移植 coding-agent **`core/extensions`** 的 **S-engine 子集**（runner + registerTool + engine 事件）；接到 Agent loop（ADR 0008） |
| **依赖** | **P3 done**；feature `agent-engine-extensions-v1` **frozen** |
| **实现计划** | [`docs/plans/P3_1_agent_engine_extensions.md`](plans/P3_1_agent_engine_extensions.md) **v0.2.3 completed** · map [`P3_1_module_map.md`](plans/P3_1_module_map.md) |
| **边界契约** | [`docs/features/agent_engine_extensions_v1.md`](features/agent_engine_extensions_v1.md) **v0.2.2** |
| **必含** | types/loader/runner/wrapper；§3.1 IN emit；AP3 挂载；M2 registerTool；SK2；H1 |
| **显式不做** | TUI/ui；session 树事件；npm/git install；Reasonix 业务包 |
| **完成标准** | Offline O1–O11 + Live L1+L2+L3a+L3b+L4；search offline 仍绿 |
| **退出条件** | §10 Offline+Live + ADR 0006 omit 仍成立 → `P3.1=done` |

### P3.2 — Pi extension capability enablement

| 项 | 内容 |
|----|------|
| **目标** | 在 P3.1 已完成 S-engine baseline 上，为已冻结 local extension consumer 补齐最小 Pi enablement（ADR 0009） |
| **依赖** | **P3.1 done**；consumer feature **frozen**；版本化 `agent-engine-extensions-v1` / P3.1 plan delta（plan D0） |
| **实现计划** | [`docs/plans/P3_2_pi_extension_capability_enablement.md`](plans/P3_2_pi_extension_capability_enablement.md) **v0.1.1** |
| **边界契约** | [`docs/features/reasonix_prefix_cache_v1.md`](features/reasonix_prefix_cache_v1.md) **v0.1.0 frozen** |
| **范围** | upstream `packages/ai` cache transport / usage parity；`packages/agent` provider-neutral `CompactionPlan` transaction；`capability_packages/reasonix_prefix_cache` consumer |
| **硬边界** | Reasonix threshold/summary/provider policy 仅在 package；不得新 hook、第二 loop、TUI、boot/environment host 产品、npm/git/home install；**无**有序 `enabled` load plan（Q21 构造性 terminal） |
| **与 search** | 无业务依赖；必须有 search + Reasonix 同载、无 collision / lifecycle interference 门禁 |
| **完成标准** | consumer feature §6 T1、extension-contract delta、upstream adapter parity tests、generic bridge tests 全绿；C8 走正式 loader/Harness 全栈路径且留存脱敏 live green 证据 |
| **退出条件** | ADR 0006/0008 omit 仍成立，P3.2 feature/plan 所列 offline 门禁全绿，且 C8 实配成功；普通 CI 可 skip live，但 skip 不能关闭 P3.2 → `P3.2=done` |

### P4 — `competitive_app`

| 项 | 内容 |
|----|------|
| **目标** | FastAPI + DDD + workflow Process Manager；引入**业务能力**（研究闭环） |
| **依赖** | **P1+P2+P3+P3.1+P3.2 done** |
| **结构** | `domain` / `application/workflow` / `adapter/in/fastapi` / `adapter/out` / `wiring` |
| **配置** | `config/settings.example.yaml` + env 覆盖密钥（D23） |
| **投影** | App SQLite（与 JSONL 史实分离） |
| **业务能力** | **不在架构契约写死清单**；P4 开工前用 §4 冻结「本期能力」 |
| **完成标准（骨架）** | ① 路由只调 application；② domain 无 IO；③ 至少一条「假业务阶段」调用真 agent+capability；④ import-linter/分层检查 |
| **退出条件** | 骨架 + 分层门禁绿；业务能力按 §4 迭代 |

---

## 3. 横切（全阶段）

| 项 | 要求 |
|----|------|
| 上游 | 只对照 **main**；PR 可附 SHA（非强制 lock） |
| 异步 | asyncio 为 pi 公开 API 默认 |
| 校验 | Pydantic v2 |
| 密钥 | 不入 git |
| 数据 | `data/` gitignore（sessions 等） |
| 文档 | 移植模块建议 `upstream: packages/...` |
| 禁止 | 第二 agent 框架；跳阶段合并；Domain 调网络 |

---

## 4. 业务能力引入（P4，单独控漂移）

架构冻结 **不等于** 业务范围冻结。

| 步骤 | 动作 |
|------|------|
| 1 | 搜索能力边界：**frozen** — [`docs/features/search_capability_packages_v1.md`](features/search_capability_packages_v1.md) **v0.1.12**（`search-capability-packages-v1`） |
| 2 | 本期已冻结能力：**三搜索 package + 五 AgentTool + Offline/Live 验收**（feature 契约 §4 / §10） |
| 3 | 业务 policy 只进 `competitive_app` + `capability_packages/*`，不进 `packages/ai|agent`；P3.2 仅允许 ADR 0009 的 provider-neutral bridge / upstream parity |
| 4 | 旧仓 = **能力参考**（非 1:1 复刻）：[`xj120/competitive-agent`](https://github.com/xj120/competitive-agent)；本地与本仓并排 `competitive-agent/`；契约 D12 / ADR 0007 / §1.3 |
| 5 | workflow Skill 自进化：feature **frozen v0.2.1** + plan [`P4_workflow_skill_self_evolution.md`](plans/P4_workflow_skill_self_evolution.md) **completed v0.1.2**；实现与验证已完成，后续变更须新建 feature/plan，不从未冻结 backlog 推断 |

**本期已冻结（search capability v1）：**

1. `capability_packages/search_tavily|search_anysearch|search_grok`  
2. Tools：`tavily_search` / `tavily_fetch` / `anysearch_search` / `anysearch_fetch` / `grok_search`  
3. 统一 `search_result.v1` / `fetch_result.v1` + Agent 可见 toolResult（feature 契约 §10）  

**仍未冻结：** 完整 fact_report schema，以及其余未单独冻结的 P4 业务能力。workflow Skill 自进化已冻结、实现并完成验证。

---

## 5. 状态板（实现时更新）

| 阶段 | 状态 | 完成日期 | 备注 |
|------|------|----------|------|
| P1 `packages/ai` | **done** | 2026-07-22 | branch `p1/packages-ai`; offline tests green |
| P2 `packages/agent` | **done** | 2026-07-23 | branch `p2/packages-agent`; offline suite green; JSONL resume smoke |
| P3 capability loader | **done** | 2026-07-23 | branch `p3/package-manager-local`; local isomorphic subset; C1 faux green |
| P3.1 agent engine extensions | **done** | 2026-07-24 | feature v0.3.0（P3.2 delta）；plan v0.2.4 remains completed；Offline 124 passed；Live 24 passed |
| P3.2 Pi extension capability enablement | **done** | 2026-07-26 | A+B+E；Offline 139 passed；full-stack Live warm-cache green；plan v0.1.2 |
| P4 `competitive_app` | **in_progress** | | HTTP 骨架（`competitive-app-http-v1` v0.3.2：20 路由 = 14 + reports×2 + SSE + trace + refine + feedback；报告列表+全文 + SSE 11 事件 + trace span + 章节批注深化 + 修正率闭环）+ 三阶段研究 workflow（`research-workflow-v1` v0.2.2 frozen；write sections + trace span；SearchOS coverage 引擎；ADR 0010 + Patch；SOCM + 并行 sub-agent + judge；搜索质量修复；offline 132 passed + live）；后续：证据库/订阅/仪表盘/澄清问卷 |
| 业务能力 v1 | **partial**（搜索 capability **done** + 研究闭环 v1 done / v2 in_progress） | 2026-07-29 | search packages + 三阶段研究 workflow v0.2.1 冻结（ADR 0010 Patch v0.2.1）；v2 引擎实现 PR2-6 + 搜索质量修复；完整 fact_report schema 仍 todo |
| P4 workflow Skill 自进化 | **done** | 2026-07-30 | App-owned Workflow Skill Overlay；Poirot frozen SHA；transplant-first；G0–F5 / O1–O16 / S1–S4 / 真实 provider L1–L4 全部完成；自动 CAPTURED、task-driven FIX、GitRatchet rollback 已接线；不改架构契约 |

状态枚举：`todo` | `in_progress` | `done` | `blocked`。

---

## 6. 漂移检查清单（每个 PR）

- [ ] 阶段是否允许本 PR 的范围？  
- [ ] 是否改了 `packages/ai|agent` 的边界/语义？若是，是否对照 main？  
- [ ] 是否把业务类型写进 agent/ai？  
- [ ] 是否引入远程 package 下载或第二内核？  
- [ ] 是否需要改架构契约（若是先 ADR）？  

---

## 7. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| 0.1.0 | 2026-07-22 | 初版：对齐契约 v0.3.1；P1–P4 门禁；业务能力延后冻结 |
| 0.1.1 | 2026-07-22 | P1 packages/ai 完成 |
| 0.1.2 | 2026-07-23 | P2 packages/agent 完成（C 档 loop+JSONL+harness；exit smoke） |
| 0.1.3 | 2026-07-23 | 契约 **0.3.2** + ADR 0006：P3 = coding-agent package **本地同构子集**；计划 v0.2 |
| 0.1.4 | 2026-07-23 | P3 capability package-manager local subset done (C0/C1) |
| 0.1.5 | 2026-07-23 | 契约 **0.3.3** + ADR 0007：钉死 P4 旧仓 `competitive-agent` 身份 |
| 0.1.6 | 2026-07-23 | 新增 `docs/FEATURES.md` 搜索 capability v1 边界草案；未解除业务实现门禁 |
| 0.1.7 | 2026-07-23 | 冻结 `docs/FEATURES.md` v0.1.11 搜索 capability v1；允许按 FEATURES 实现三包五工具 |
| 0.1.8 | 2026-07-23 | 新增搜索 capability 实现计划 `docs/plans/P4_search_capability_packages.md` v0.1.0 |
| 0.1.9 | 2026-07-23 | Feature 边界迁入 `docs/features/`；废止 `docs/FEATURES.md`；搜索契约 `search_capability_packages_v1.md` |
| 0.1.10 | 2026-07-23 | 搜索 capability packages 实现完成（三包五工具；offline O1–O6 + live） |
| 0.1.11 | 2026-07-24 | **P3.1** 入路线图；feature `agent-engine-extensions-v1` frozen v0.2.0；ADR 0008 + 契约 0.3.4；计划初版 |
| 0.1.12 | 2026-07-24 | P3.1 计划格式对齐 P3/P4（v0.2.0）；增补 `P3_1_module_map.md` |
| 0.1.13 | 2026-07-24 | P3.1 验收加完整 Live + Offline 高覆盖；feature/plan **v0.2.1** |
| 0.1.14 | 2026-07-24 | P3.1 Live 收紧 L3a/L3b 双钩子必过；feature/plan **v0.2.2** |
| 0.1.15 | 2026-07-24 | P3.1 extension runtime done：AP3/M2/H1/SK2；Offline+Live exit green；search contract v0.1.12 |
| 0.1.16 | 2026-07-26 | **ADR 0009 / contract 0.3.5**：新增 P3.2 Pi extension capability enablement，位于 P3.1 与 P4；Reasonix 不归 P4 App |
| 0.1.17 | 2026-07-26 | **P3.2**：Reasonix feature **v0.1.0 frozen**；新增 plan `P3_2_pi_extension_capability_enablement.md` v0.1.0 |
| 0.1.18 | 2026-07-26 | P3.2 plan v0.1.1：C8 收紧为正式 loader/Harness 全栈 live close gate；普通 CI 可 skip，但关闭阶段必须有脱敏 green 证据 |
| 0.1.19 | 2026-07-26 | P3.2 implementation started；D0 publishes extension feature v0.3.0 + P3.1 plan v0.2.4 delta without reopening P3.1 |
| 0.1.20 | 2026-07-26 | P3.2 done：Reasonix prefix cache A+B+E；Offline 139 passed；full-stack Live warm-cache green；plan v0.1.2 completed |
| 0.1.21 | 2026-07-26 | P4 `competitive_app` → **in_progress**：HTTP 骨架切片落地（feature `competitive-app-http-v1` frozen v0.1.3；14 路由；DDD 分层门禁；offline 19+124 passed）；研究 workflow 仍占位 |
| 0.1.22 | 2026-07-26 | 六阶段研究 workflow 落地（feature `research-workflow-v1` frozen v0.1.1；替换占位 runner；24 决策；offline 35+124 passed）；`competitive-app-http-v1` 升 v0.2.0 |
| 0.1.23 | 2026-07-26 | research-workflow-v1 plan **completed** v0.1.1：L1 live 真搜索验证（DeepSeek + tavily/anysearch/grok；165s；六阶段全 ok；报告非空）；修 5 个 live bug；全仓 offline 159 passed |
| 0.1.24 | 2026-07-28 | **research-workflow-v1 v0.2.0 frozen（ADR 0010 / 契约 0.3.6）**：六阶段→三阶段（plan/search/write）+ SearchOS coverage 引擎复现（SOCM + 并行 sub-agent + Extraction + Sensor）；反转 F-R2/F-R3/F-R7/F-R10（局部）；`competitive-app-http-v1` 升 v0.3.0（投影 stages 6→3 + coverage）；PR1 文档冻结，实现 PR2-6 |
| 0.1.25 | 2026-07-29 | **research-workflow-v1 v0.2.1 patch frozen（ADR 0010 Patch v0.2.1）**：搜索质量第一步修复——接通 `mark_unknown`（UNKNOWN 可达）+ junk/低置信过滤 + actionable/satisfied 谓词 + judge prompt 禁占位/多源抽取 + plan 结构化 queries + subtask 拆细；局部反转 D-S3/D-S6/D-S8"一轮单源"默认；三阶段vs六阶段对比实验两题三阶段均优（源权威性 87%/31% vs 47%/13%、0 junk）；不动 D*/G* 核心、不碰 packages/ai\|agent |
| 0.1.26 | 2026-07-29 | **competitive-app-http-v1 v0.3.1 frozen（对齐 VerdaAI 第一批）**：新增 3 路由（`GET /reports` 卡片列表 + `GET /reports/{task_id}` 结构化全文 + `GET /tasks/{id}/stream` SSE 流式 11 事件）；report_id 复用 task_id；卡片字段 runner 完成时落 projection；全文实时组装（JSONL+SOCM）；SSE state_snapshot + 15s heartbeat + 断连任务继续；emit_event 透传链；created_at 空串 bug 修复；14 路由不破坏、不动 D*/G*；offline 117 passed |
| 0.1.27 | 2026-07-30 | **http v0.3.2 + research-workflow v0.2.2 frozen（对齐 VerdaAI 第二批）**：新增 3 路由（`GET /tasks/{id}/trace` span 列表 + `POST /reports/{id}/refine` 章节重写 + `POST /reports/{id}/feedback` 修正率）；write 产物加 `sections`（后端从 report 切）；trace span 记录（LLM 调用包夹 emit span → SQLite `task_spans`，轻量无全文，不推 SSE）；refine append stage_output（守 D24）；feedback `report_feedback` 表（修正率不进 projection）；TaskService 加 models 参数；17 路由不破坏、不动 D*/G*；offline 132 passed |
| 0.1.28 | 2026-07-30 | 新增 `workflow-skill-self-evolution-v1` v0.1.0-draft：记录 App-owned Workflow Skill Overlay；核心要求为在现有架构内 copy-first 移植 Poirot Skill L1/L2/L3（module map + 最小 host glue + MIT attribution），只进化 workflow 未固定策略；G1–G29 待 grilling；未 frozen、无 plan、禁止实现；不动架构契约 v0.3.6 |
| 0.1.29 | 2026-07-30 | `workflow-skill-self-evolution-v1` 升 v0.2.0-draft：完成 G1–G29 grilling；冻结 Poirot SHA 与 transplant-first 边界，四 scope/版本固定、FIX+CAPTURED、Poirot eval/自动 promotion/effective-rate rollback、原表+companion tables、capability active manifest、删除/并发/预算/安全边界均 resolved；明确不自行增加 benchmark、DERIVED、manual capture、prompt-injection 防护或 crash recovery；待最终冻结审阅，无 plan，禁止实现；架构契约仍 v0.3.6 |
| 0.1.30 | 2026-07-30 | 用户确认冻结 `workflow-skill-self-evolution-v1` v0.2.0：G1–G29、Poirot frozen SHA、transplant-first module map、FIX/CAPTURED、四 scope、数据/文件/晋升/回滚/删除/并发/预算/安全边界正式生效；架构契约保持 v0.3.6；实现计划待建，尚未开始实现 |
| 0.1.31 | 2026-07-30 | 建立 [`P4_workflow_skill_self_evolution.md`](plans/P4_workflow_skill_self_evolution.md) v0.1.0 active：逐文件 COPY/ADAPT/REWRITE/OMIT/NEW-HOST module map；A foundation→B 四 scope 注入硬门→C Eval→D Evolution→E lifecycle→F verification；O1–O16 + S1–S4 + L1–L2；feature 做无语义 patch 至 v0.2.1，校正 learned Skill 文件树；implementation not started，架构契约仍 v0.3.6 |
| 0.1.32 | 2026-07-30 | P4 workflow Skill 自进化实现完成：feature v0.2.1 implementation verified；plan v0.1.0 completed；O1–O16、S1–S4、L1–L2 green；packages/ai|agent 与架构契约未改 |
| 0.1.33 | 2026-07-30 | 补齐真实运行时链路：feedback→refine→CAPTURED、completed task→FIX cycle、四 scope live binding、cycle 内 GitRatchet rollback；L1–L4 green；架构契约与 packages/ai|agent 未改 |
