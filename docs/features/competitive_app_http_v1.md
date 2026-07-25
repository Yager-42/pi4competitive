# Feature 边界契约：competitive-app-http-v1

| 字段 | 值 |
|------|-----|
| **feature_contract_version** | `0.2.0` |
| **status** | **frozen** |
| **updated** | 2026-07-26 |
| **feature_id** | `competitive-app-http-v1` |
| **roadmap_stage** | **P4** `competitive_app` —— 应用骨架 + HTTP 接口边界（研究 workflow 仍占位） |
| **architecture_contract** | [`ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.4**（§3.2 / §6.3 / §7 / D8 / G1 / G2 / D24 / D25） |
| **roadmap** | [`ROADMAP.md`](../ROADMAP.md) §2 P4 / §4 业务能力引入 |
| **plan** | [`docs/plans/P4_competitive_app_http.md`](../plans/P4_competitive_app_http.md) |
| **path** | `docs/features/competitive_app_http_v1.md` |
| **参考源（非上游）** | 旧仓 [`xj120/competitive-agent`](https://github.com/xj120/competitive-agent) **`rr-refactor`** —— P4 能力参考（D12 / ADR 0007），非 1:1 复刻 |

---

## 0. 效力与状态

1. 本文是 **P4 `competitive_app` HTTP 接口边界** 的 **frozen** 功能边界（grill 收敛于 2026-07-25，25 个决策点见 §8）。
2. 标为 **locked** 的决定不得由实现者自行改写；变更须重新 grill 并升 `feature_contract_version`，并同步 Roadmap。
3. §6 验收标准为 **locked**；实现须满足，不得缩水。
4. 变更本边界 = 业务范围变更，须同步 `docs/ROADMAP.md`。
5. 本文不改变架构契约；分层、依赖方向、技术栈仍以架构契约为最高约束。
6. **研究阶段 workflow 骨架仍未冻结**（Roadmap §0 / §4）：本 feature 只交付**接口壳 + 占位 runner**，真研究流程待后续 feature grill 冻结后升级本文至 v0.2.0+。

---

## 1. 动机与目标（locked grill）

### 1.1 问题

本仓 P1–P3.1 已完成：`pi_ai`（模型层）+ `pi_agent`（agent 引擎 + JSONL session + capability 包）。但 **P4 `competitive_app` 仍只有 `.gitkeep`**，无 FastAPI / 无业务层 / 无 HTTP 入口。

用户要把旧仓 `competitive-agent` `rr-refactor` 分支的后端 HTTP 接口搬过来。但旧仓是**能力参考**（ADR 0007），不能原样复刻：
- 旧仓 `backend/agent/**`（自写 pi-style 运行时）= 禁忌，本仓已有 `pi_agent`（G3 第二内核）；
- 旧仓 SQLite transcript = 违反 D24（JSONL 才是 SoT）；
- 旧仓 research 三步强契约 / 7 组运营接口 = 绑定未冻结或未规划能力。

### 1.2 目标（locked）

1. 在 `competitive_app/` 建出契约要求的 **DDD 骨架**（`adapter/in/fastapi` → `application/workflow` → `domain` → `adapter/out/persistence` + `wiring`）。
2. 把旧仓 rr-refactor 的 HTTP 接口里**合规可搬的**接到底层 `pi_agent`，拿到一条 "HTTP → app → agent → JSONL" 的真实路径。
3. **对话史实**走本仓 `JsonlSessionRepo`（`data/sessions/`），**任务投影 + session 索引**走 App SQLite（契约 §7 投影，非对话史实）。
4. 研究 workflow **占位**：接口形态完整可测，但不假装真跑研究流程。

### 1.3 非目标（locked grill）

| 不做 | 说明 |
|------|------|
| 真研究 workflow（六阶段 / DAG / 报告 schema） | 未冻结（Roadmap §0）；本 feature 只交付占位 runner |
| research 前置 2 接口（resolve-target / discover-competitors） | grill 决定砍掉：占位阶段前三步断、壳是摆设；task 入参调用方自构造 |
| 旧仓 memory 模块 / `/memory/consolidate` | 用户决定不管；rr-refactor 也已移除 |
| 旧仓 `backend/agent/**` 任何代码 | 禁忌（G3）；底座用本仓 `pi_agent` |
| 旧仓 SQLite transcript（`TranscriptRepository`） | 违反 D24；改 JSONL + SQLite 投影双层 |
| 旧仓 7 组运营接口（quality/observability/evaluations/candidates/skills/rollouts/settings） | 旧仓产品线，本仓 roadmap 未规划；不搬 |
| session 级 `/events` 接口 | grill 砍掉：本仓无工作流事件表，硬凑误导（§3.3） |
| 完整报告渲染（`reporting/`） | 报告 schema 未冻结；`/report` 返回 stub |
| `max_turns` 限制 | grill 砍掉：本仓 `Agent` 不消费此字段（§4.1） |
| 升架构契约版本 | 纯 P4 app 骨架，不改 D*/G*；不改 import 映射 |

---

## 2. 规范源与角色（locked grill）

| 来源 | 角色 | 约束 |
|------|------|------|
| 本仓 `earendil_works.pi_agent`（Agent / AgentHarness / Session / JsonlSessionRepo / LocalFileSystem / AbortController） | **底座 SoT** —— 会话、prompt、abort、JSONL 持久化 | 不复制第二内核（G3） |
| 本仓 `earendil_works.pi_ai`（create_models / ModelsImpl / providers / faux） | **模型层 SoT** —— stream_fn 注入（`models.streamSimple`） | `ModelsImpl` app 级单例 |
| 本仓 `package_manager`（load_capability_packages / apply_capability_report） | **capability 加载** —— 挂 echo/search tools | lifespan 加载一次，LoadReport 缓存 |
| 旧仓 `competitive-agent` `rr-refactor` `backend/api/__init__.py` | **接口形态参考** —— 路由路径 / DTO / RuntimeRegistry 模式 | 非规范源；重写不抄；D12/ADR 0007 |
| 旧仓 rr-refactor `workflows/competitive/models.py`（`WorkflowTaskRequest`） | **任务入参形态参考** | research_brief/competitor_discovery 粗定义（§4.2） |
| 旧仓 rr-refactor `backend/agent/**` | **禁止** | 禁忌 |
| 旧仓 rr-refactor `TranscriptRepository` / `TranscriptProjector` | **禁止直接搬** | 违反 D24；投影逻辑重写 |

**旧仓身份（D12 / ADR 0007）：** 远程 `https://github.com/xj120/competitive-agent`，本地并排 `competitive-agent/`，分支 `rr-refactor`。**仅** P4 业务/接口形状参考，**非** Pi 父本（Pi 父本仍仅为 `earendil-works/pi` main）。

---

## 3. 搬运范围与裁切（locked grill）

### 3.1 搬运范围

| 档 | 旧仓 rr-refactor 接口 | 本 feature | 策略 |
|----|----------------------|-----------|------|
| 🟢 直接搬 + 换底座 | sessions（5）+ health（1） | **搬** | 底座换本仓 `pi_agent`；持久化换 JSONL |
| 🟡 搬壳 + 占位 | tasks（7） | **搬壳** | 入参跟 rr-refactor 结构；占位 runner |
| 🔴 不搬 | 旧仓 research 前置（2）+ session/events（1）+ task/events（1）+ 7 组运营（28） | **不搬** | grill 砍 / 未规划 |

### 3.2 接口清单（locked）—— 共 14 路由，前缀 `/api/v2`

**B 组 — Agent 会话（5，🟢 真实）**

| 方法 路径 | 作用 | 底座 / 语义 |
|----------|------|------------|
| `POST /sessions` | 建会话（model/system_prompt/metadata） | `AgentHarness` + `JsonlSessionRepo.create`；返回 session_id + status |
| `GET /sessions/{id}` | 会话状态 | SQLite 索引 + JSONL metadata |
| `POST /sessions/{id}/prompt` | 发消息跑一轮（**同步等完**） | `harness.agent.prompt` + `wait_for_idle`；返回最后一条 assistant message（§4.4） |
| `POST /sessions/{id}/abort` | 中止（当前 + 排队） | `harness.agent.abort()`；被取消的排队请求返 409（§5.3） |
| `GET /sessions/{id}/messages` | 消息历史（原始透传，不分页） | `session.build_context()` messages |

**A 组 — 研究任务（8，🟡 占位）**

| 方法 路径 | 作用 | 策略 |
|----------|------|------|
| `POST /tasks` | 建研究任务（research_brief + competitor_discovery + metadata） | 占位 runner；202；**固定返回 status=pending**；不建 session |
| `GET /tasks` | 列任务 | SQLite 投影 |
| `GET /tasks/{id}` | 单任务 | SQLite 投影 |
| `POST /tasks/{id}/resume` | 恢复 | completed → 返回 completed；非终态 → 重起占位 runner |
| `POST /tasks/{id}/abort` | 中止 | 边界 case：终态 task 返回 aborted 不改 status |
| `DELETE /tasks/{id}` | 删除 | 删 SQLite + **连带删关联 session**（JSONL + 索引） |
| `GET /tasks/{id}/report` | 报告 | **stub**（`report=null` + 未冻结注） |
| `GET /tasks/{id}/sessions` | 子 session 列表 | 占位阶段返回空列表（task 不建 session） |

**Health（1，🟢）**

| 方法 路径 | 作用 |
|----------|------|
| `GET /health` | 健康检查（active_workflows 计数） |

### 3.3 不出现在本 feature 公开 API（locked）

- 旧仓 7 组运营接口（quality / observability / evaluations / candidates / skills / rollouts / settings）
- research 前置 2 接口（resolve-target / discover-competitors）
- `POST /memory/consolidate` 及任何 memory 子系统
- session 级 `/events`、task 级 `/events`（本仓无工作流事件表）
- 旧仓 `AgentState` / `AgentEvent` / `TranscriptRepository` / `TranscriptProjector` 旧类型
- 真 research workflow runner / 报告 schema / evidence_id 生成

---

## 4. 请求/响应契约（locked grill）

### 4.1 `SessionCreateRequest`（locked）

```python
class SessionCreateRequest(BaseModel):  # extra="forbid"
    model: str = ""            # 空 → 用 wiring 默认 model；非空 → 查 pi_ai catalog，查不到 422
    system_prompt: str = ""    # 空 system prompt
    metadata: dict[str, Any] = {}
```

**砍掉 `max_turns`**（grill）：本仓 `Agent` / `AgentLoopConfig` 无此字段，收了不消费。prompt turn 数不限（靠模型 stopReason）。

### 4.2 `WorkflowTaskRequest`（locked；占位粗定义）

```python
class WorkflowTaskRequest(BaseModel):  # extra="forbid"
    research_brief: dict[str, Any]            # 粗定义；不深建 rr-refactor 子结构
    competitor_discovery: dict[str, Any]      # 粗定义
    metadata: dict[str, Any] = {}             # 自由业务元数据
```

- 顶层结构校验（Pydantic 类型/必填/extra forbid）；
- **不实现**旧仓跨字段强校验（decisions-cover / context_fingerprint / target 一致性）——占位无数据来源；
- `research_brief` / `competitor_discovery` 内部子结构留 workflow feature 冻结时定；
- 代码标 `PLACEHOLDER — 强校验待 workflow feature 冻结`。

### 4.3 model 解析（locked）

| 入参 `model` | 行为 |
|--------------|------|
| 空 `""` | 用 wiring 配的默认 model（从 settings/env，如 `OPENAI_MODEL`） |
| 非空 | 查 `pi_ai` builtin catalog；查到用；**查不到 422** |
| — | **不开放**传完整 Model dict；catalog 外 model 留后续 settings 配置 |

### 4.4 `POST /sessions/{id}/prompt` 响应（locked）

同步等完（`await harness.agent.prompt(content) + wait_for_idle()`）。返回：

```json
{
  "session_id": "...",
  "message": { "...最后一条 role=assistant 的 message dict..." },
  "status": "..."
}
```

- `message` = `agent.state.messages` 中最后一条 `role == "assistant"` 的原始 dict 透传（含 content blocks / usage / stopReason）；
- 无 assistant message（异常）→ `message: null`；
- 失败（缺 key / 模型错）→ **200 + message.errorMessage**（走 `Agent._handle_run_failure`，失败编码进 stream，不抛 503）；
- prompt 本身**不限 turn / 不设超时**（grill；本 feature 骨架可接受，超时/限 turn 留后续）。

### 4.5 配置（locked；对齐 D23 + search feature §4.3）

- provider key / url / model 走环境变量（`.env`，gitignored）；
- `config/settings.example.yaml`：
  ```yaml
  capability_packages:
    enabled:
      - echo_example          # 默认仅 echo；search_* 按 .env 配齐按需启用
  sessions:
    cwd: competitive_app      # 钉死常量；所有 app session 落 data/sessions/--competitive_app--/
  app_db: data/app.db
  prompt_lock_timeout: 30     # 排队超时秒
  ```
- App SQLite 路径 = `data/app.db`（`data/` gitignored）；
- 不复用 `CAPABILITY_PACKAGES_ENABLED` env（search feature §4.3）。

---

## 5. 持久化与真相源（locked grill —— 契约 §7 / D24 / D25）

### 5.1 双层

| 数据 | 权威 | 落点 |
|------|------|------|
| 对话 / tool / session 树（messages） | **JSONL** @ `data/sessions/--competitive_app--/`（D24/D25） | 本仓 `JsonlSessionRepo`（`LocalFileSystem(cwd="competitive_app")`），不改 |
| 任务投影（status/进度） | **App SQLite** @ `data/app.db` | `adapter/out/persistence/`，**非对话史实** |
| session 索引（id→file_path + 配置） | **App SQLite** | 同上；resume 依赖此索引 |
| task ↔ session 映射 | `tasks.session_id` 列 | 占位阶段为 null（task 不建 session） |
| 内存 running | 非 SoT | `runtime_registry` 仅跟踪在途 |

### 5.2 SQLite schema（locked）

```sql
create table tasks (
    task_id          text primary key,
    session_id       text,                -- 关联 JSONL session；占位阶段 null
    query            text not null,       -- display_title(research_brief) 或占位
    status           text not null,       -- pending|running|aborted|completed|failed
    created_at       text not null,
    updated_at       text not null,
    metadata_json    text not null,       -- 调用方业务元数据（独立列）
    projection_json  text not null        -- app 投影快照（status/进度/usage 汇总）
);
create index idx_tasks_status on tasks(status, created_at);

create table sessions (
    session_id       text primary key,
    file_path        text not null,       -- JSONL 文件路径（resume 用）
    cwd              text not null,       -- 重建 LocalFileSystem 用（钉死 competitive_app）
    model            text not null,       -- resume 重建 harness 用
    system_prompt    text not null,
    created_at       text not null
);
```

**不存**对话 messages / events（那在 JSONL）。这是对旧仓 "SQLite 当 transcript" 的合规反转。

### 5.3 并发与 abort 语义（locked grill）

- **Agent 实例缓存**：`runtime_registry` 按 session_id 缓存 `Agent` 实例（复用，避免重复 open JSONL）；
- **per-session `asyncio.Lock`**：同一 session 的 prompt 串行；并发请求**排队等**；
- **排队超时** `prompt_lock_timeout`（默认 30s）→ 超时返 **409 Conflict**；
- **abort 语义**：`POST /sessions/{id}/abort` 中止当前正在跑的 prompt **+ 取消所有排队请求**；被取消的排队请求返 **409 Conflict**（reason: session aborted）；
- **prompt 本身不设超时**（§4.4）；锁超时仅管排队等待，不管 prompt 执行。

### 5.4 delete 连带（locked grill）

`DELETE /tasks/{id}`：删 SQLite task 记录 + **连带删关联 session**（`JsonlSessionRepo.delete` + SQLite sessions 索引行）。不提供单独的 `DELETE /sessions/{id}`（删除路径只走 task）。

---

## 6. 验收标准（locked）

### 6.1 Offline（默认 CI 必绿）

| ID | 要求 |
|----|------|
| O1 | `import competitive_app` 成功；DDD 目录结构存在（domain/application/adapter/wiring） |
| O2 | **分层门禁**（AST 扫）：`domain/` 无 fastapi/aiosqlite/pi_agent import（允许 pydantic）；`adapter/in/fastapi/` 无 pi_agent/pi_ai/aiosqlite import（只调 application） |
| O3 | 14 路由全部注册（`TestClient` + `/openapi.json` 断言路径集合 = §3.2） |
| O4 | `POST /sessions` + `POST /sessions/{id}/prompt`（faux + echo tool）→ 200；响应含最后一条 assistant message；JSONL 落 `data/sessions/--competitive_app--/`；`GET /sessions/{id}/messages` 含归一化内容 |
| O5 | 并发 `POST /sessions/{id}/prompt`：第二个排队等；超时（短 timeout 测试）返 409 |
| O6 | `POST /tasks`（ResearchBrief + metadata）→ 202 + `status=pending`；`GET /tasks/{id}` 返回 projection（status + current_stage + per-stage）；`GET /tasks/{id}/report` 返回 write 产物（research-workflow-v1 F-R12）；`GET /tasks/{id}/sessions` 返回单元素（task 建一个 session） |
| O7 | `POST /tasks/{id}/resume`（completed task）→ 返回 completed；failed/aborted → 接着跑（research-workflow-v1 F-R16）；`POST /tasks/{id}/abort` → aborted；`DELETE /tasks/{id}` → 删 SQLite + 关联 session |
| O8 | `POST /sessions/{id}/abort` 中止在途 prompt（faux）；排队请求被取消返 409 |
| O9 | **resume**：新实例 load JSONL session（经 SQLite 索引取 file_path+cwd+model+system_prompt）→ 重建 `AgentHarness` → 同 session_id 继续可 prompt（faux） |
| O10 | capability：`enabled=["echo_example"]` 时 echo tool 可被 agent 调用（faux prompt 触发 tool call） |
| O11 | model 解析：`model=""` → 用默认；`model="<catalog id>"` → 用该 model；`model="<不存在>"` → 422 |
| O12 | 启动分层失败：缺 provider key 不阻断启动（prompt 时 200+errorMessage）；capability 包加载失败不拖垮（记 diagnostic）；SQLite/JSONL 基础设施故障 → lifespan 抛错 |

测试落点：`tests/competitive_app/{contract,unit,integration}`。

### 6.2 Live（可选，非 exit-blocking）

| ID | 要求 |
|----|------|
| L1 | `.env` 配真实 provider key；`POST /sessions/{id}/prompt` 打真网；响应 `message` 非空、`stopReason ∈ {stop, length, toolUse}` |
| L2 | 无 key 时 live 测试 **skip**（`@pytest.mark.live` + 无 key skip），不得伪绿 |

### 6.3 实现完成定义

- Offline O1–O12 全绿；
- 分层契约测试绿（O2）；
- 本仓 P1–P3.1 离线套件仍绿（无回归）；
- **不**宣称真研究 workflow / 报告 schema / memory 就绪。

---

## 7. 分层与依赖方向（locked grill —— 契约 §3.2 / §6.3 / G1 / G2）

```text
adapter/in/fastapi  →  application/workflow  →  domain
        │                     │
        │                     └──→ packages/agent → packages/ai
        │                     └──→ adapter/out/persistence（SQLite 投影 + 索引）
        └──（不直接调 pi_agent / pi_ai / aiosqlite）
```

| 层 | 允许 import | 禁止 import |
|----|------------|------------|
| `domain/` | stdlib、pydantic | fastapi、aiosqlite、pi_agent、pi_ai、competitive_app 其他层 |
| `application/` | domain、pi_agent、adapter/out store 具体类、typing | fastapi、aiosqlite（不直接碰 DB，走 adapter/out） |
| `adapter/in/fastapi/` | fastapi、application、dto | pi_agent、pi_ai、aiosqlite |
| `adapter/out/persistence/` | aiosqlite、domain | fastapi、pi_agent、pi_ai |
| `wiring.py` | 全部（依赖汇点） | 无 |

| 规则 | 约束 |
|------|------|
| `domain/` | 纯值对象 + 状态机；**无** fastapi/aiosqlite/pi_agent import（G1）；允许 pydantic |
| `adapter/in/fastapi/` | 只调 `application/`；**不**编排 workflow；**不**直接碰 pi_agent/SQLite（G2） |
| `application/` | 编排：调 pi_agent + adapter/out store；Process Manager 在此；直接 import store 具体类（骨架优先，不搞端口接口） |
| `adapter/out/persistence/` | SQLite 投影 + 索引 store；单连接 + `asyncio.Lock` 串行化写；只被 application 调 |
| `wiring.py` | 组装：`ModelsImpl` 单例 + stream_fn + capability + repo + harness factory；lifespan 持有 |
| `packages/agent\|ai` | **↛** `competitive_app.domain`（契约 §3） |
| `capability_packages/*` | **↛** `competitive_app.domain`（G5） |

---

## 8. 决策记录（grill 收敛，25 项）

| ID | 状态 | 决定 |
|----|------|------|
| F-A1 | locked | `competitive_app` DDD 骨架；`adapter/in/fastapi` → `application/workflow` → `domain` → `adapter/out/persistence` + `wiring` |
| F-A2 | locked | **14 路由**前缀 `/api/v2`：sessions(5) + tasks(8) + health(1)（grill 砍 research 2 + session/events 1 + task/events 1） |
| F-A3 | locked | 底座 = 本仓 `pi_agent`（Agent/AgentHarness/Session/JsonlSessionRepo/LocalFileSystem）；不搬旧仓 agent |
| F-A4 | locked | 对话史实 = JSONL @ `data/sessions/--competitive_app--/`；任务投影 + session 索引 = App SQLite @ `data/app.db` |
| F-A5 | locked | session 索引表 `sessions(session_id, file_path, cwd, model, system_prompt, created_at)`；resume 重建 harness（JSONL 只存 messages） |
| F-A6 | locked | cwd 钉死常量 `competitive_app`；`LocalFileSystem(cwd="competitive_app")` |
| F-A7 | locked | `ModelsImpl` app 级单例；`stream_fn = models.streamSimple`；provider 由 wiring 配（默认 openai，faux 测试用 faux_provider） |
| F-A8 | locked | `POST /sessions` model 空 → 默认；非空查 catalog，查不到 422；不开放传完整 Model dict |
| F-A9 | locked（v0.2.0 修订） | capability lifespan 加载一次；LoadReport 缓存；per-session apply；默认白名单 `[echo_example, search_tavily, search_anysearch, search_grok]`（search 包按 .env 配齐启用；research-workflow-v1 F-R19 需搜索工具） |
| F-A10 | locked | Agent 实例缓存进 `runtime_registry`；per-session `asyncio.Lock` 排队；超时 30s 返 409 |
| F-A11 | locked | abort 中止当前 + 取消排队；被取消排队请求返 409 |
| F-A12 | locked | `DELETE /tasks/{id}` 连带删关联 session；不提供 `DELETE /sessions/{id}` |
| F-A13 | locked | 砍 session `/events` + task `/events`：本仓无工作流事件表 |
| F-A14 | locked | 砍 research 前置 2 接口：占位前三步断、壳是摆设；task 入参调用方自构造 |
| F-A15 | locked（v0.2.0 修订） | `WorkflowTaskRequest` 入参为 `ResearchBrief`（简化：`{target, goal, competitors, dimensions}`，见 research-workflow-v1 F-R6）；不再粗定义 dict |
| F-A16 | locked（v0.2.0 修订） | task runner = 六阶段 `ResearchRunner`（research-workflow-v1）；`POST /tasks` 固定返回 `status=pending`，runner 异步跑六阶段；占位 runner 已替换 |
| F-A17 | locked（v0.2.0 修订） | task 创建即建 session（1:1，六阶段在该 session 跑）；`GET /tasks/{id}/sessions` 返回单元素列表；`task.session_id` 非 null |
| F-A18 | locked | resume/abort 走边界 case：completed task resume 返回 completed；终态 task abort 返回 aborted 不改 status |
| F-A19 | locked | `POST /sessions/{id}/prompt` 同步等完；返回最后一条 assistant message（无则 null）；失败 200+errorMessage（不 503） |
| F-A20 | locked | `GET /sessions/{id}/messages` 原始 message dict 透传（含 content blocks），全部历史，不分页 |
| F-A21 | locked | `SessionCreateRequest` 砍 `max_turns`（本仓 Agent 不消费）；3 字段 |
| F-A22 | locked | `tasks` 表 `metadata_json` 独立列（与 projection_json 分列） |
| F-A23 | locked | 启动分层失败：缺 key 不阻断（prompt 时 200+errorMessage）；包失败记 diagnostic；基础设施故障 lifespan 抛错 |
| F-A24 | locked | SQLite 单连接 + `asyncio.Lock` 串行化写（写操作锁内完整）；读不加锁 |
| F-A25 | locked | 分层禁令：domain 禁 fastapi/aiosqlite/pi_agent（允许 pydantic）；adapter/in 禁 pi_agent/pi_ai/aiosqlite；application 直接 import store 具体类（不搞端口） |

---

## 9. 冻结记录

| 项 | 值 |
|----|-----|
| 冻结版本 | `0.2.0` |
| 冻结日期 | 2026-07-26 |
| grill | 25 决策点收敛（§8 F-A1…F-A25）；v0.2.0 由 research-workflow-v1 修订 F-A9/F-A15/F-A16/F-A17 |
| 验收 | §6 Offline O1–O12 + Live L1–L2 |
| 架构影响 | 无；不升 `ARCHITECTURE_CONTRACT` |
| Roadmap | 见 `docs/ROADMAP.md` §5（P4 → in_progress） |
| 关联 | research-workflow-v1 落地后，task 路由行为从占位变真（F-A16）；report 返回 write 产物（F-A8 stub 已替换） |

### 9.1 修订

| 版本 | 日期 | 说明 |
|------|------|------|
| 0.1.0 | 2026-07-25 | 草案：P4 app 骨架 + 16 路由边界；参考旧仓 rr-refactor；workflow 占位 |
| 0.1.1 | 2026-07-25 | **grill frozen**：25 决策收敛；路由 16→13（砍 research/events）；加 sessions 索引表 + per-session 锁 + abort 排队 + delete 连带 + model 解析 + 启动分层失败 + 分层禁令；占位 task 不建 session |
| 0.1.2 | 2026-07-25 | 物理布局确认：**src layout**（`competitive_app/src/competitive_app/...`），与本仓 `packages/ai|agent` 一致；契约 §6.4 为逻辑布局示意，import 名仍为 `competitive_app`（§6.5），不违规 |
| 0.1.3 | 2026-07-25 | 路由数勘误：tasks 实为 8 个（POST/GET list/GET one/resume/abort/DELETE/report/sessions），总数 13→**14**（O3 / F-A2 同步） |
| 0.2.0 | 2026-07-26 | **research-workflow-v1 落地**：task runner 从占位换成六阶段 `ResearchRunner`；修订 F-A9（白名单加 search 包）/ F-A15（ResearchBrief 简化模型替代粗定义 dict）/ F-A16（六阶段 runner 替代占位）/ F-A17（task 建 session 1:1 替代 null）；O6/O7 更新为真实行为；占位测试已替换 |
