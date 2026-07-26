# Plan: P4 — Research workflow v1（六阶段，替换占位 runner）

| Field | Value |
|-------|--------|
| **plan_id** | `P4-research-workflow` |
| **plan_version** | `0.1.1` |
| **status** | **completed** |
| **created** | 2026-07-26 |
| **updated** | 2026-07-26 |
| **roadmap** | [`docs/ROADMAP.md`](../ROADMAP.md) stage **P4** `competitive_app` |
| **contract** | [`docs/contracts/ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.4** |
| **feature** | [`docs/features/research_workflow_v1.md`](../features/research_workflow_v1.md) **v0.1.1 frozen** — `research-workflow-v1`（24 决策 F-R1…F-R24） |
| **ADR** | [0007 legacy repo reference](../contracts/adr/0007-legacy-repo-capability-reference.md) |
| **depends_on** | **`competitive-app-http-v1` v0.1.x**（HTTP 骨架已落地）；P1+P2+P3+P3.1 done |
| **reference** | 旧仓 `competitive-agent` **`rr-refactor`** `workflows/competitive/{runner,models,profiles}.py`（结构同构 + 行为重写） |
| **target** | `competitive_app/src/competitive_app/{domain,application/workflow}/` |
| **tests** | `tests/competitive_app/integration/`（扩展现有）+ `tests/competitive_app/unit/` |
| **non_goal** | stage retry；多角色评审；缺口补搜；stage 回退；前置 2 接口；per-stage 模型；fan-out 并发；旧仓完整产物模型；下沉 packages/agent |

---

## 0. Purpose

1. 同构旧仓 rr-refactor **六阶段** `STAGES=(plan,collect,analyze,write,review,cite)`，用本仓 `pi_agent` 重写。
2. 替换 `competitive-app-http-v1` v0.1.x 的**占位 runner**（`task_service._run_placeholder`）→ `ResearchRunner.run()`。
3. 每个 stage = 一次 `agent.prompt`（统一执行模型）；agent loop 内调 capability tool 完成搜集。
4. stage 产物进 JSONL（D24 SoT）；task 状态/进度进 SQLite 投影（feature §7）。
5. `GET /tasks/{id}/report` 返回 write 真报告；resume 接着跑；abort 双层停。
6. 同步升级 `competitive-app-http-v1` → v0.2.0。

**Approach:** 结构同构旧仓六阶段（STAGES + 主循环 + 依赖门禁），行为用本仓 `pi_agent` 重写；旧仓代码只参考不抄。非 1:1 复刻（D12/ADR 0007）。

**Non-goals of this plan:**

| Out of scope | Why |
|--------------|-----|
| stage 内 retry | F-R3：失败→failed |
| 多角色评审 + 投票 | F-R11：单 reviewer |
| 缺口补搜 / stage 回退 | F-R3：严格顺序 |
| 前置 2 接口 | F-R5：research_brief 调用方构造 |
| per-stage 模型 / fan-out 并发 | F-R7/F-R2：单模型、串行 |
| 旧仓完整产物模型 | F-R10：每 stage 最小 schema |
| 下沉 `packages/agent` | D8 禁止 |

---

## 1. Binding constraints (contract for implementers)

| ID | Must |
|----|------|
| Feature v0.1.1 | F-R1…F-R24 + §3–§8 — **no inventing open scope** |
| D8 / §3.2 | 六阶段落 `competitive_app/`；**不**碰 `packages/agent` |
| G1 / F-A25 | `domain/` 无 fastapi/aiosqlite/pi_agent（允许 pydantic） |
| G2 / F-A25 | `adapter/in/` 只调 application（不改路由层） |
| G3 | 唯一 agent 内核 = `pi_agent`；不搬旧仓 agent |
| D24 / §7 | stage 产物 = JSONL；task 状态/进度 = SQLite 投影 |
| F-R2 | 每 stage = 一次 `agent.prompt`；agent loop 调 tool |
| F-R3 | 严格顺序 + 依赖/输入门禁；失败→failed；不 retry/回退 |
| F-R8 | 一个 harness 跑六阶段；每 stage 前过滤 `agent.state.tools` |
| F-R16 | resume 接着跑（跳过已 ok stage） |
| F-R21 | 双层 abort（agent.abort + 循环边界检查） |
| F-R22 | 直接替换占位 runner；接口不变 |
| F-R24 | 同步升 `competitive-app-http-v1` → v0.2.0 |

**Prerequisite check (gate G0):**

```bash
.venv/bin/pytest tests/competitive_app tests/packages tests/capability_loader -m "not live" -q
```

---

## 2. 复用的本仓能力（不重造）

| 能力 | 来源 | 用途 |
|------|------|------|
| `Agent` / `AgentHarness` | `pi_agent` | 跑 stage prompt；`agent.state.tools` setter 过滤工具（F-R8） |
| `Session.append_custom_message_entry` | `pi_agent.harness.session` | 存 stage 产物（custom_type="stage_output"） |
| `Session.build_context` | `pi_agent.harness.session` | 读前序 stage 产物（F-R9） |
| `AbortController` / `agent.abort` | `pi_agent` | abort 当前 stage（F-R21） |
| `capability_packages/search_*` | `capability_packages/` | collect/cite 搜索工具（动态挑，F-R19） |
| `TaskProjectionStore` | `competitive_app.adapter.out` | task 状态/进度（projection_json） |
| `RuntimeRegistry` | `competitive_app.application.workflow` | task active 检查 + abort（F-R18/F-R21） |

**参考（不抄）旧仓 rr-refactor：**
- `workflows/competitive/runner.py` — STAGES 主循环 + 依赖门禁结构
- `workflows/competitive/models.py` — STAGES 定义 + 产物模型（简化）
- `workflows/competitive/profiles.py` — per-stage profile（去掉模型区分）

---

## 3. 目标文件（新增/修改）

```text
competitive_app/src/competitive_app/
  domain/
    research_brief.py            # 改：ResearchBrief 简化模型（F-R6）
    stage.py                     # 新：STAGES + StageResult 最小 schema（F-R10）
  application/workflow/
    research_runner.py           # 新：六阶段 Runner（F-R1/F-R2/F-R3）
    profiles.py                  # 新：per-stage profile + system prompt 常量（F-R20）
    stage_outputs.py             # 新：stage 产物存/取 JSONL（F-R4/F-R9）
    task_service.py              # 改：_run_placeholder → ResearchRunner.run（F-R22）
  adapter/in_/fastapi/
    dto.py                       # 改：WorkflowTaskRequest 用 ResearchBrief 模型（F-A15 v0.2.0）
config/settings.example.yaml     # 改：默认白名单加 search 包（F-A9 v0.2.0）
```

**不改**：`packages/ai|agent`、路由层（routes_tasks.py 行为不变，只是 service 行为变真）。

---

## 4. 状态板（update as you go）

Status: `todo` | `in_progress` | `done` | `blocked`。

| Step | Phase | Status | Note |
|------|-------|--------|------|
| G0 | P4 http v0.1.x + P1–P3.1 离线绿（前置） | done | |
| A1 | domain/stage.py：STAGES + StageResult schema | done | F-R1/F-R10 |
| A2 | domain/research_brief.py：ResearchBrief 简化模型 | done | F-R6 |
| A3 | application/workflow/profiles.py：6 个 profile + system prompt | done | F-R20 |
| A4 | application/workflow/stage_outputs.py：产物存/取 JSONL | done | F-R4/F-R9 |
| B1 | application/workflow/research_runner.py：六阶段主循环 + 门禁 | done | F-R2/F-R3 |
| B2 | research_runner：per-stage 工具过滤 + 数据传递 | done | F-R8/F-R9 |
| B3 | research_runner：产物 schema 校验 + 容错解析 | done | F-R10 |
| B4 | research_runner：projection 更新（current_stage + per-stage） | done | F-R13 |
| B5 | research_runner：双层 abort（agent.abort + 循环检查） | done | F-R21 |
| B6 | research_runner：resume 接着跑（跳过已 ok） | done | F-R16/F-R17 |
| C1 | task_service：_run_placeholder → ResearchRunner.run | done | F-R22 |
| C2 | dto.py：WorkflowTaskRequest 用 ResearchBrief | done | F-A15 |
| C3 | settings.yaml：默认白名单加 search 包 | done | F-A9 |
| D0 | 单元测试：STAGES/StageResult schema/ResearchBrief 校验 | done | |
| D1 | 集成测试：六阶段 completed + 产物全在 JSONL | done | O1/O2 |
| D2 | 集成测试：依赖门禁 failed + report + sessions | done | O3/O4/O5/O6 |
| D3 | 集成测试：abort + resume 接着跑 + 并发 409 | done | O7/O8/O9 |
| D4 | 集成测试：capability 搜索工具 + 降级 | done | O10 |
| D5 | 契约测试：分层门禁仍绿 + packages/agent 无改动 | done | O11 |
| D6 | 改占位测试：task 真跑六阶段（faux） | done | O12 |
| D7 | Live 测试（L1/L2，env-gated） | done | L1 live 真搜索验证过（DeepSeek + tavily/grok）|
| D8 | 升 competitive-app-http-v1 → v0.2.0；roadmap/features 索引同步 | done | F-R24 |

**Rules:**
- 不在 B1 前动 task_service（runner 先稳）。
- 占位 runner 测试（test_tasks.py）在 D6 一次性改。
- 不改 `packages/ai|agent`。

---

## 5. 分阶段步骤

### Phase A — domain + profiles + stage_outputs

**A1. domain/stage.py** — `STAGES = ("plan","collect","analyze","write","review","cite")`；`StageResult` dataclass（`stage, ok, output, error`）；每 stage 最小 schema 常量（§5 of feature）。纯，允许 pydantic。

**A2. domain/research_brief.py** — `ResearchBrief(BaseModel)`：`target: TargetIdentity`（`{name, category?}`）、`goal: str`、`competitors: list[str]`（≥1）、`dimensions: list[str]`（≥1），`extra="forbid"`。

**A3. application/workflow/profiles.py** — 6 个 `StageProfile`（`name, system_prompt, tool_names`）：
- plan/analyze/write/review：`tool_names=[]`（不给搜索工具）；
- collect/cite：`tool_names=None`（动态挑 `*_search`/`*_fetch`，F-R19）。
- system prompt 硬编码常量（F-R20）。

**A4. application/workflow/stage_outputs.py** — `append_stage_output(session, stage, output)`（custom_message entry）+ `get_stage_output(session, stage)`（从 build_context 提取指定 stage 产物）。

**Exit A:** domain/profiles/stage_outputs 就位；纯函数可单测。

### Phase B — ResearchRunner

**B1. research_runner.py** — `ResearchRunner(task_id, session, agent, store, registry, profiles, research_brief)`。
- `run(start_stage=None)`：`for name in STAGES:` 若 `start_stage` 且 name 在 start_stage 之前 → skip（F-R16）；每 stage 开头检查 abort + 依赖门禁（F-R3/F-R21）。
- 每 stage：设 `agent.state.tools`（F-R8）→ 拼 prompt（含前序产物，F-R9）→ `agent.prompt(content)` + `wait_for_idle` → 解析产物（F-R10）→ `append_stage_output`（F-R4）→ 更新 projection（F-R13）。

**B2.** per-stage 工具过滤：`collect/cite` 动态从 `all_tools` 挑 `name.endswith("_search") or name.endswith("_fetch")`（F-R19）。

**B3.** 产物解析：try JSON 解析 agent 最后一条 assistant message 的 text → 校验 schema；失败 → fallback（`{stage: "raw", raw: text}`），stage 仍算过（F-R10 容错）。

**B4.** projection：每 stage 前设 `current_stage` + `stages[name]="running"`；后设 `ok/failed`；存 `tasks.projection_json`。

**B5.** abort：runner 持 `abort_signal`；循环每 stage 开头 `if aborted: break`；被 cancel 时 finally `agent.abort()`（F-R21）。

**B6.** resume：`run(start_stage=first_non_ok_stage)`（从 projection 读）；已 ok 的 skip（F-R16）。

**Exit B:** runner 能跑六阶段（faux）。

### Phase C — 接入 task_service

**C1. task_service.py** — `create_task`：建 session（`repo.create` + SQLite 索引，`task.session_id` 非 null）→ 起 `ResearchRunner.run` via `registry.start_task`（F-R22）。`resume_task`：读 projection 找 first non-ok stage → `ResearchRunner.run(start_stage=...)`（F-R16）。`abort_task`：`registry.abort_task`（cancel Task + agent.abort，F-R21）。`get_report`：从 session 提 write stage_output（F-R12）。`get_task_sessions`：返回单元素（F-R14）。

**C2. dto.py** — `WorkflowTaskRequest`：`research_brief: ResearchBrief`（不再是 dict，F-A15 v0.2.0）。

**C3. settings.yaml** — 默认白名单 `[echo_example, search_tavily, search_anysearch, search_grok]`（F-A9 v0.2.0）。

**Exit C:** task 路由行为变真；接口不变。

### Phase D — 测试

**D0.** 单元：STAGES 常量、StageResult schema、ResearchBrief 校验（extra forbid / competitors ≥1）。

**D1–D4.** 集成（见 §6 测试清单）。

**D5.** 契约：分层 AST 扫描仍绿（domain 无 pi_agent；runner 在 application）；`packages/agent` git diff 为空。

**D6.** 改 `test_tasks.py`：占位断言（秒翻 completed）→ 真跑六阶段断言（等 faux 跑完 completed）。

**D7.** Live：真 provider + search key 跑六阶段。

**D8.** 升 `competitive-app-http-v1` v0.2.0；roadmap §5 业务能力 v1 注记；features/README + agents.md 索引同步。

---

## 6. 测试策略

| 层 | 路径 | 断言 | Feature § |
|----|------|------|-----------|
| Unit | `tests/competitive_app/unit/` | STAGES / schema / ResearchBrief | §6.1 O2 |
| Integration | `tests/competitive_app/integration/` | 六阶段端到端（faux + mock search tool） | §6.1 O1–O12 |
| Live（可选） | `tests/competitive_app/integration/live/` | 真网六阶段 | §6.2 L1–L2 |

### 6.1 Offline 测试（默认 CI 必绿，O1–O12）

| ID | 测试 | 构造 + 断言 |
|----|------|------------|
| O1 | `test_six_stages_completed` | faux model（每 stage 按最小 schema 返回 JSON）+ mock search tool；`POST /tasks` → 202；等 runner 跑完 → `GET /tasks/{id}` status==completed；`GET /sessions/{id}/messages` 含 6 个 stage_output custom message |
| O2 | `test_stage_output_schema` | 每个 stage 产物含必填字段（plan.plan / collect.evidence / analyze.analysis / write.report / review.verdict / cite.citations）；缺字段 → stage failed |
| O3 | `test_dependency_gate_failed` | 让 plan stage 产物空（faux 返回空）→ collect 不跑；task status==failed；projection.stages.plan=="failed" |
| O4 | `test_report_returns_write_output` | 六阶段跑完 → `GET /tasks/{id}/report` → `{task_id, status:"completed", stage:"write", report:"<md>"}`；write 未跑时（人为 fail 在 analyze）→ report==null |
| O5 | `test_task_sessions_single` | `POST /tasks` → `GET /tasks/{id}/sessions` → 单元素列表；`task.session_id` 非 null |
| O6 | `test_projection_progress` | 跑到 collect 中途（慢 faux）→ `GET /tasks/{id}` projection.current_stage=="collect"；stages.plan=="ok"，stages.collect=="running" |
| O7 | `test_abort_stops_runner` | 跑到 collect 中途 → `POST /tasks/{id}/abort` → status==aborted；后续 stage（analyze及之后）不跑；projection 停在 collect |
| O8 | `test_resume_continues` | abort 后 → `POST /tasks/{id}/resume` → 从 collect 重跑（plan skip）；跑完 completed；completed task resume → 返回 completed；running task resume → 409 |
| O9 | `test_concurrent_resume_409` | task running 时并发 2 个 resume → 第二个 409 |
| O10 | `test_capability_search_tools` | collect stage agent 拿到 mock search tool（`*_search`）；白名单无 search 包时 collect 降级（不 fail，evidence 可能空） |
| O11 | `test_layering_and_no_pi_change` | AST 扫描：domain 无 pi_agent；`git diff --exit-code packages/` 为空（packages/agent 无改动） |
| O12 | `test_placeholder_replaced` | task 不再秒翻 completed；`POST /tasks` 后 status 经 pending→running→completed（非瞬间）；旧占位测试已删/改 |

### 6.2 Live 测试（可选，非 exit-blocking）

| ID | 测试 | 构造 + 断言 |
|----|------|------------|
| L1 | `test_live_six_stages_real` | `.env` 配真实 provider + 至少一个 search key；`POST /tasks` 真跑六阶段打真网；`GET /tasks/{id}/report` 返回非空 markdown（write.report 非空）；`GET /tasks/{id}` status==completed |
| L2 | `test_live_skip_without_key` | 无 key 时 live skip，不伪绿 |

### 6.3 命令

```bash
.venv/bin/pytest tests/competitive_app -m "not live" -q          # offline
.venv/bin/pytest tests/competitive_app/contract -q               # 分层门禁（快）
.venv/bin/pytest tests/competitive_app -m live --maxfail=1       # live
```

---

## 7. 风险

| Risk | Mitigation |
|------|------------|
| faux model 不按 JSON schema 输出 | 测试用定制 faux response（每 stage 返回固定 JSON）；handler 容错解析（F-R10） |
| agent 在不该搜的 stage 调搜索工具 | per-stage 过滤 `agent.state.tools`（F-R8）；plan/analyze/write/review 无搜索工具 |
| resume 跳过逻辑读错 stage | projection.stages 明确 ok/failed/pending；resume 从 first non-ok 开始（F-R16） |
| abort 时 agent.prompt 卡住 | `agent.abort()` 触发 AbortController；runner Task cancel（F-R21） |
| stage 产物大撑爆 JSONL | 已接受（search feature §8.3 完整正文不截断）；v1 不缓解 |
| 替换占位 runner 破坏现有 task 测试 | D6 一次性改 test_tasks.py（F-R22） |
| 环境无 uv/Python 3.12 | 不依赖本机验证；交付后 `uv run pytest` |

---

## 8. Definition of Done

- [x] §4 状态板 G0–D8 = `done`
- [x] Feature §6.1 Offline O1–O12 全绿
- [x] `competitive-app-http-v1` 升 v0.2.0（F-A9/F-A15/F-A16/F-A17 修订）
- [x] P1–P3.1 + app http 离线套件无回归（除 D6 改的占位测试）
- [x] `packages/agent|ai` 零改动（git diff 空）
- [x] 14 路由不变（行为变真）
- [x] **不**宣称多角色评审/缺口补搜/retry 就绪
- [x] L1 live 验证过（DeepSeek + tavily/grok 真搜索；六阶段全 ok；报告非空）

---

## 9. 与后续 feature 的边界

```text
本 feature：六阶段研究 workflow（单 reviewer / 串行 / 不 retry / 不回退）
后续 1：多角色评审 + 投票共识（review 升级）
后续 2：证据缺口自动补搜（analyze → 回 collect）
后续 3：前置 2 接口（resolve-target / discover-competitors）
后续 4：报告图表 / chart_requirements
```

本 feature 留稳定 `ResearchRunner.run(start_stage=)` 接口，使后续 feature 能扩展（多 reviewer / 补搜）而不改路由层。

---

## 10. 修订记录

| Version | Date | Note |
|---------|------|------|
| 0.1.0 | 2026-07-26 | 草案：六阶段研究 workflow；24 决策；替换占位 runner；offline O1–O12 + live L1–L2 |
| 0.1.1 | 2026-07-26 | **completed**：实现落地 + 测试全绿。Offline 35（competitive_app）+ 159（全仓）passed；L1 live 真搜索验证（DeepSeek + tavily/anysearch/grok，165s，六阶段全 ok，报告非空）。修 5 个 live bug（model 手搓 / try 范围 / .env 加载 / 容错解析 / 白名单 None）。状态板 G0–D8 全 done。 |
