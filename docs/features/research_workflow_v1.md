# Feature 边界契约：research-workflow-v1

| 字段 | 值 |
|------|-----|
| **feature_contract_version** | `0.1.1` |
| **status** | **frozen** |
| **updated** | 2026-07-26 |
| **feature_id** | `research-workflow-v1` |
| **roadmap_stage** | **P4** `competitive_app` —— 六阶段研究 workflow（替换占位 runner） |
| **architecture_contract** | [`ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.4**（§3.2 / D8 / G1 / G2 / D24） |
| **roadmap** | [`ROADMAP.md`](../ROADMAP.md) §2 P4 / §4 业务能力引入 |
| **plan** | [`docs/plans/P4_research_workflow.md`](../plans/P4_research_workflow.md) |
| **path** | `docs/features/research_workflow_v1.md` |
| **参考源（非上游）** | 旧仓 [`xj120/competitive-agent`](https://github.com/xj120/competitive-agent) **`rr-refactor`** `backend/workflows/competitive/`（D12/ADR 0007；结构同构 + 行为重写，非 1:1 复刻） |
| **关系** | 落地后同步升级 [`competitive-app-http-v1`](competitive_app_http_v1.md) → **v0.2.0**（修订 F-A8/F-A15/F-A16/F-A17/F-A9 占位表述） |

---

## 0. 效力与状态

1. 本文是 **P4 六阶段研究 workflow** 的 **frozen** 功能边界（grill 收敛于 2026-07-26，24 决策见 §8）。
2. 标为 **locked** 的决定不得由实现者自行改写；变更须重新 grill 并升 `feature_contract_version`。
3. §6 验收标准为 **locked**。
4. 变更本边界 = 业务范围变更，须同步 `docs/ROADMAP.md`。
5. 本文不改变架构契约；六阶段代码落 `competitive_app/`（§3），不下沉 `packages/agent`（D8 禁止）。
6. **本 feature 替换 `competitive-app-http-v1` v0.1.x 的占位 runner**；落地后 http feature 升 v0.2.0。

---

## 1. 动机与目标（locked grill）

### 1.1 问题

`competitive-app-http-v1` v0.1.x 的 task 路由是**占位**（F-A16）：`POST /tasks` 起占位 runner 秒翻 completed，不跑 agent、不建 session、`/report` 返回 stub。研究 workflow 当时未冻结。

本 feature 冻结六阶段研究 workflow，替换占位 runner，让 `POST /tasks` 真跑研究流程、出真报告。

### 1.2 目标（locked）

1. 同构旧仓 rr-refactor **六阶段** `STAGES = (plan, collect, analyze, write, review, cite)`，行为重写用本仓 `pi_agent`。
2. 每个 stage = 一次 `agent.prompt`，统一执行模型；agent loop 内部调 capability tool 完成搜集。
3. stage 产物进 JSONL session（D24 SoT）；task 状态/进度进 SQLite 投影（§7）。
4. `GET /tasks/{id}/report` 返回 write stage 真报告（不再是 stub）。
5. resume 接着跑（跳过已 ok 的 stage），abort 后可 resume。

### 1.3 非目标（locked grill）

| 不做 | 说明 |
|------|------|
| stage 内 retry | grill 砍（F-R3）：失败 → failed，不自动重试 |
| 多角色评审 + 投票共识 | grill 砍（F-R11）：review = 单 reviewer 一次 prompt |
| 证据缺口自动补搜 | grill 砍：analyze 产 gaps 但 v1 不触发回 collect |
| stage 回退（review 没过回 write） | grill 砍（F-R3）：严格顺序，不回退 |
| 前置 2 接口（resolve-target / discover-competitors） | grill 砍（F-R5）：research_brief 由调用方构造 |
| per-stage 模型 | grill 砍（F-R7）：全 task 一个模型 |
| collect fan-out 并发搜集 | grill 砍（F-R2）：agent 串行调 tool |
| 旧仓完整产物模型（CollectionDecision/EvidenceGap/AnalysisPosition/...） | grill 砍（F-R10）：每 stage 最小 schema |
| 下沉 `packages/agent` | D8 禁止：六阶段是业务，留 `competitive_app` |
| 报告图表 / chart_requirements | 旧仓绑定 report schema，v1 不做 |

---

## 2. 规范源与角色（locked grill）

| 来源 | 角色 | 约束 |
|------|------|------|
| 旧仓 rr-refactor `workflows/competitive/runner.py` | **六阶段结构参考**（STAGES / StageDefinition / 主循环） | 结构同构，行为重写 |
| 旧仓 rr-refactor `workflows/competitive/models.py` | **STAGES 定义 + 产物模型参考** | STAGES 同；产物模型简化（§5） |
| 旧仓 rr-refactor `workflows/competitive/profiles.py` | **per-stage profile 参考** | profile 简化（不区分模型，F-R7） |
| 本仓 `earendil_works.pi_agent` | **底座**（Agent/AgentHarness/Session/AbortController） | 不复制第二内核（G3） |
| 本仓 `capability_packages/search_*` | **collect/cite 搜索工具来源** | 动态挑 search 类 tool（F-R19） |
| 本仓 `competitive-app-http-v1` | **HTTP 入口**（task 路由不变，行为变真） | 落地后升 v0.2.0 |
| 旧仓 `workflows/competitive/research_brief.py` | **ResearchBrief 结构参考** | 简化（F-R6） |

**旧仓身份（D12/ADR 0007）：** 远程 `https://github.com/xj120/competitive-agent`，分支 `rr-refactor`。**仅**结构/行为参考，**非** Pi 父本。

---

## 3. 落点（locked grill —— 契约 §3.2 / D8）

六阶段代码全部在 `competitive_app/`，**不**碰 `packages/agent`（D8 禁止）：

```text
competitive_app/src/competitive_app/
  domain/
    research_brief.py          # ResearchBrief 简化模型（F-R6）
    stage.py                   # STAGES + StageResult 最小 schema（F-R10）
  application/workflow/
    research_runner.py         # 六阶段 Runner（替换 task_service 占位）
    profiles.py                # per-stage profile（prompt 模板 + tool_names）+ system prompt 常量（F-R20）
    stage_outputs.py           # stage 产物存/取 JSONL（custom_message entry）
```

| 层 | 落点 | 约束 |
|----|------|------|
| `domain/` | STAGES / ResearchBrief / StageResult schema | 纯，无 fastapi/aiosqlite/pi_agent（G1） |
| `application/workflow/` | Runner / profiles / stage_outputs | 调 pi_agent + adapter/out store；Process Manager |
| `packages/agent\|ai` | **不改** | 六阶段不下沉 |

---

## 4. 执行模型（locked grill）

### 4.1 统一一次 prompt（F-R2）

每个 stage = 一次 `agent.prompt(content)`，统一执行模型：
- 六阶段 = 六次 prompt（review 也是单 reviewer 一次，F-R11）；
- agent loop 内部自己调 capability tool（collect stage agent 发 toolCall 调搜索工具）；
- 不写 fan-out 调度（v1 串行）。

### 4.2 严格顺序 + 门禁（F-R3）

`for name in STAGES:` 严格顺序，每 stage 开头检查：
- **依赖门禁**：前置 stage 必须 ok，否则 task `failed`（reason=dependency_failed）；
- **输入门禁**：该 stage 依赖的前序产物必须在 session 里，否则 `failed`（reason=missing_input）；
- **abort 检查**：被 abort 则 break，task `aborted`（F-R21）。

stage 跑完检查**产物非空**（plan 有 plan / collect 有 evidence / ... / cite 有 citations），空 → `failed`。**不**自动 retry、**不**回退。

### 4.3 per-stage 工具集（F-R8）

一个 harness 跑六阶段（同一 session），每 stage 跑前按 `profile.tool_names` 过滤 `agent.state.tools`：
- plan / analyze / write / review：不给搜索工具；
- collect / cite：给搜索工具（动态挑已加载的 `*_search`/`*_fetch` tool，F-R19）。

### 4.4 数据传递（F-R9）

后续 stage prompt 前，从 `session.build_context()` 提取依赖的前序 stage_output 产物，handler 显式格式化进 prompt 文本（不让 agent 自己从 messages 找）。

---

## 5. 产物 schema（locked grill —— F-R10）

每 stage 最小 JSON schema，agent prompt 强制按 schema 输出，handler 容错解析（解析失败 → 原始文本塞 fallback 字段，stage 仍算过）：

| stage | 产物 schema |
|-------|------------|
| plan | `{"plan": str}` |
| collect | `{"evidence": list[{"source": str, "content": str}]}` |
| analyze | `{"analysis": str, "gaps": list[str]}`（gaps 仅记录，v1 不补搜） |
| write | `{"report": str}`（markdown） |
| review | `{"verdict": str, "issues": list[str]}` |
| cite | `{"citations": list[{"claim": str, "source": str}]}` |

产物存进 JSONL `custom_message` entry（`custom_type="stage_output"`，content=产物 dict，details=`{"stage": name}`）。

---

## 6. 验收标准（locked）

### 6.1 Offline（默认 CI 必绿）

| ID | 要求 |
|----|------|
| O1 | `ResearchRunner` 跑六阶段（faux model + echo/搜索 mock tool）→ task `completed`；六 stage 产物全在 JSONL |
| O2 | stage 产物 schema 校验：每 stage 产物含必填字段（plan.plan / collect.evidence / ... / cite.citations） |
| O3 | 依赖门禁：人为让 plan 失败 → collect 不跑，task `failed`（reason=dependency_failed） |
| O4 | `GET /tasks/{id}/report` 返回 write 产物（`{task_id, status, stage:"write", report:"<md>"}`）；write 未跑 → `report:null` |
| O5 | `GET /tasks/{id}/sessions` 返回单元素（task 创建即建 session，`session_id` 非 null） |
| O6 | projection 进度：`GET /tasks/{id}` 返回 `projection.current_stage` + `stages` per-stage status（pending/running/ok/failed） |
| O7 | abort：`POST /tasks/{id}/abort` 中止在途 task → `aborted`；当前 stage agent loop 停 + 后续 stage 不跑 |
| O8 | resume 接着跑：failed/aborted task resume → 从第一个非 ok stage 继续（跳过已 ok）；completed resume → 返回 completed；running resume → 409 |
| O9 | 并发 resume 同一 task → 第二个 409（F-R18） |
| O10 | capability：collect/cite stage 拿到已加载的 search 类 tool；没配 key 时 collect 降级（不 fail） |
| O11 | 分层门禁仍绿：六阶段代码落 `competitive_app`，`packages/agent` 无改动（F-R3 落点） |
| O12 | `competitive-app-http-v1` 占位测试已改：task 不再秒翻 completed，真跑六阶段 |

### 6.2 Live（可选，非 exit-blocking）

| ID | 要求 |
|----|------|
| L1 | `.env` 配真实 provider + 至少一个 search key；`POST /tasks` 真跑六阶段打真网；`/report` 返回非空 markdown |
| L2 | 无 key 时 live skip，不伪绿 |

### 6.3 实现完成定义

- Offline O1–O12 全绿；
- `competitive-app-http-v1` 升 v0.2.0（占位项修订）；
- P1–P3.1 + app http v0.1.x 离线套件无回归（除被替换的占位测试）。

---

## 7. 持久化与状态（locked grill）

### 7.1 双层（对齐 http feature §5）

| 数据 | 权威 | 落点 |
|------|------|------|
| 六阶段 prompt messages + stage 产物 | **JSONL** @ `data/sessions/--<cwd>--/` | pi_agent `Session.append_custom_message_entry` |
| task 状态 + 进度投影 | **SQLite** `tasks.projection_json` | `adapter/out/persistence/` |
| session 索引 | SQLite `sessions` 表 | http feature §5.2（不变） |

### 7.2 projection_json schema（F-R13）

```json
{
  "current_stage": "collect",
  "stages": {
    "plan": "ok", "collect": "running", "analyze": "pending",
    "write": "pending", "review": "pending", "cite": "pending"
  }
}
```
stage status 枚举：`pending` / `running` / `ok` / `failed`。runner 每 stage 切换更新 SQLite。

### 7.3 终态（F-R15）

| 终态 | 触发 |
|------|------|
| `completed` | 六 stage 全 ok |
| `failed` | stage 验收失败 / 依赖门禁不过 |
| `aborted` | 用户 abort（cancel runner Task + agent.abort，F-R21） |

---

## 8. 决策记录（grill 收敛，24 项）

| ID | 状态 | 决定 |
|----|------|------|
| F-R1 | locked | 同构旧仓六阶段 `STAGES=(plan,collect,analyze,write,review,cite)`；结构同构 + 行为重写（非 1:1 抄） |
| F-R2 | locked | 统一执行模型：每 stage = 一次 `agent.prompt`；agent loop 内调 capability tool；v1 串行 |
| F-R3 | locked | 严格顺序 + 依赖/输入门禁；失败→failed；不 retry、不回退、不 resume 跳过（注：F-R16 修正 resume 跳过） |
| F-R4 | locked | stage 产物全进 JSONL（custom_message）；SQLite 存状态/进度/索引 |
| F-R5 | locked | 不加前置 2 接口；research_brief 调用方构造（后端只消费） |
| F-R6 | locked | ResearchBrief 简化：`{target, goal, competitors:list[str], dimensions:list[str]}`；不建旧仓 breadth/depth/evidence_policy/chart_requirements |
| F-R7 | locked | 全 task 一个模型（wiring 默认）；`POST /tasks` 不传 model；profile 不区分模型 |
| F-R8 | locked | 一个 harness 跑六阶段；每 stage 前按 `profile.tool_names` 过滤 `agent.state.tools` |
| F-R9 | locked | 后续 stage 从 `session.build_context()` 提取依赖产物，handler 显式拼 prompt |
| F-R10 | locked | 每 stage 最小 JSON schema（§5）；agent 强制按 schema 输出；handler 容错解析 |
| F-R11 | locked | review = 单 reviewer 一次 prompt，产 `{verdict, issues}`；不触发回退 |
| F-R12 | locked | `GET /tasks/{id}/report` 返回 write 产物 + `{task_id, status, stage, report}` |
| F-R13 | locked | task.status 四态；进度进 `projection_json`（current_stage + per-stage status） |
| F-R14 | locked | task 创建即建 session（1:1）；`GET /tasks/{id}/sessions` 返回单元素 |
| F-R15 | locked | 三终态：completed/failed/aborted；abort = cancel Task + agent.abort |
| F-R16 | locked | resume 接着跑（跳过已 ok stage，从第一个非 ok 继续）——修正 F-R3 的"不 resume 跳过" |
| F-R17 | locked | abort 后能 resume（aborted ∈ 可 resume 态） |
| F-R18 | locked | 同 task 并发 resume → 409（复用 `registry.task_active`） |
| F-R19 | locked | 默认白名单加 search 包；collect/cite 动态挑已加载 `*_search`/`*_fetch` tool |
| F-R20 | locked | system prompt 硬编码 `application/workflow/profiles.py`；不走 capability prompts |
| F-R21 | locked | 双层 abort：agent.abort() 停当前 stage + runner 循环边界检查停后续 |
| F-R22 | locked | 直接替换占位 runner（`_run_placeholder` → `ResearchRunner.run()`）；接口不变；占位测试改 |
| F-R23 | locked | feature_id = `research-workflow-v1`；独立于 `competitive-app-http-v1` |
| F-R24 | locked | 落地后同步升 `competitive-app-http-v1` → v0.2.0（修订 F-A8/F-A15/F-A16/F-A17/F-A9） |

---

## 9. 冻结记录

| 项 | 值 |
|----|-----|
| 冻结版本 | `0.1.1` |
| 冻结日期 | 2026-07-26 |
| grill | 24 决策收敛（§8 F-R1…F-R24） |
| 验收 | §6 Offline O1–O12 + Live L1–L2 |
| 架构影响 | 无；不升 `ARCHITECTURE_CONTRACT` |
| Roadmap | 见 `docs/ROADMAP.md` §5（业务能力 v1 研究闭环落地） |
| 关联 | `competitive-app-http-v1` 升 v0.2.0 |

### 9.1 修订

| 版本 | 日期 | 说明 |
|------|------|------|
| 0.1.0 | 2026-07-26 | 草案：六阶段研究 workflow |
| 0.1.1 | 2026-07-26 | **grill frozen**：24 决策；六阶段同构 + 统一一次 prompt + 顺序门禁 + 产物进 JSONL + 简化 ResearchBrief + 单模型 + per-stage 工具 + resume 接着跑 + 替换占位 runner |
