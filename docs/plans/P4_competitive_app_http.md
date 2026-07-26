# Plan: P4 — `competitive_app` HTTP 骨架（参考旧仓 rr-refactor，契约合规）

| Field | Value |
|-------|--------|
| **plan_id** | `P4-competitive-app-http` |
| **plan_version** | `0.2.0` |
| **status** | **active** |
| **created** | 2026-07-25 |
| **updated** | 2026-07-25 |
| **roadmap** | [`docs/ROADMAP.md`](../ROADMAP.md) stage **P4** `competitive_app` |
| **contract** | [`docs/contracts/ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.4** |
| **feature** | [`docs/features/competitive_app_http_v1.md`](../features/competitive_app_http_v1.md) **v0.1.1 frozen** — `competitive-app-http-v1`（25 决策 F-A1…F-A25） |
| **ADR** | [0007 legacy repo reference](../contracts/adr/0007-legacy-repo-capability-reference.md)（旧仓=能力参考） |
| **depends_on** | **P1+P2+P3+P3.1 done**（`pi_ai` / `pi_agent` / `package_manager` / `extensions`） |
| **reference** | 旧仓 `competitive-agent` **`rr-refactor`** `backend/api/__init__.py` + `workflows/competitive/models.py`（D12/ADR 0007；非 1:1 复刻） |
| **target** | `competitive_app/` → import `competitive_app` |
| **tests** | `tests/competitive_app/`（contract / unit / integration；Offline O1–O12 + Live L1–L2） |
| **non_goal** | 真 research workflow；research 前置 2 接口；memory 模块；旧仓 agent 内核 / SQLite transcript；7 组运营接口；报告 schema；session/task `/events`；`max_turns` |

---

## 0. Purpose

1. 在 `competitive_app/` 建出契约 **§3.2 / §6.3** 要求的 **DDD 骨架**（`adapter/in/fastapi` → `application/workflow` → `domain` → `adapter/out/persistence` + `wiring`）。
2. 把旧仓 rr-refactor 后端 **14 个合规路由**接到底层 `pi_agent`，拿到 "HTTP → app → agent → JSONL" 真实路径。
3. **对话史实**走 `JsonlSessionRepo`（`data/sessions/--competitive_app--/`）；**任务投影 + session 索引**走 App SQLite（`data/app.db`），合规反转旧仓 SQLite-as-transcript。
4. 研究 workflow **占位**：占位 runner 秒翻 completed，不跑 agent、不写 JSONL、不建 session。
5. 分层门禁（G1/G2）+ 契约测试落地。

**Approach:** 参考旧仓 rr-refactor 接口形态，重写不抄；底座全用本仓 `pi_agent`。非 port、非 1:1 复刻（D12/ADR 0007）。

**Non-goals of this plan:**

| Out of scope | Why |
|--------------|-----|
| 真 research workflow（六阶段 / DAG / 报告） | 未冻结（Roadmap §0）；占位 runner |
| research 前置 2 接口（resolve-target / discover-competitors） | grill 砍（feature F-A14）：占位前三步断 |
| session/task `/events` 接口 | grill 砍（feature F-A13）：本仓无工作流事件表 |
| memory 模块 / `/memory/consolidate` | 用户决定不管；rr-refactor 已移除 |
| 旧仓 `backend/agent/**` | 禁忌（G3 第二内核） |
| 旧仓 `TranscriptRepository` / `TranscriptProjector` | 违反 D24；重写为 JSONL + SQLite 投影 |
| 旧仓 7 组运营接口 | 旧仓产品线，roadmap 未规划 |
| 报告 schema / `reporting/` | 未冻结；`/report` stub |
| `max_turns` 限制 | grill 砍（feature F-A21）：本仓 Agent 不消费 |
| 升架构契约版本 | 纯 P4 app 骨架，不改 D*/G* |

---

## 1. Binding constraints (contract for implementers)

| ID | Must |
|----|------|
| Feature v0.1.1 | F-A1…F-A25 + §3–§8 — **no inventing open scope** |
| D8 / §3.2 | `competitive_app` DDD + 六边形；Runner 在 Application；Domain 无 IO |
| G1 / F-A25 | `domain/` 无 fastapi/aiosqlite/pi_agent import（允许 pydantic） |
| G2 / F-A25 | `adapter/in/fastapi/` 不编排 workflow；只调 `application/`；不直接碰 pi_agent/pi_ai/aiosqlite |
| §3 / G7 | `packages/agent\|ai` ↛ `competitive_app.domain`；`capability_packages/*` ↛ `competitive_app.domain` |
| G3 | 唯一 agent 内核 = `pi_agent`；不搬旧仓 agent |
| D24 / D25 / §7 / F-A4 | 对话史实 = JSONL @ `data/sessions/--competitive_app--/`；任务投影 + session 索引 = App SQLite @ `data/app.db` |
| F-A5 | `sessions` 索引表存 file_path/cwd/model/system_prompt；resume 重建 harness |
| F-A6 | `LocalFileSystem(cwd="competitive_app")` 钉死 |
| F-A7 | `ModelsImpl` app 级单例；`stream_fn = models.streamSimple` |
| F-A10 / F-A11 | per-session `asyncio.Lock` 排队；超时 30s 返 409；abort 中止当前 + 取消排队 |
| F-A12 | `DELETE /tasks/{id}` 连带删关联 session；无 `DELETE /sessions/{id}` |
| F-A16 / F-A17 | 占位 runner 秒翻 completed；不跑 agent/不写 JSONL/不建 session；`POST /tasks` 固定返回 pending |
| F-A19 | `POST /prompt` 同步等完；返回最后一条 assistant message；失败 200+errorMessage（不 503） |
| F-A23 | 启动分层失败：缺 key 不阻断；包失败记 diagnostic；基础设施故障 lifespan 抛错 |
| F-A24 | SQLite 单连接 + `asyncio.Lock` 串行化写 |
| D23 / search §4.3 | provider 配置走 env；capability 启用走 `settings.yaml` 白名单 |
| D12 / ADR 0007 | 旧仓 rr-refactor = 能力参考；重写不抄；非 Pi 父本 |
| F-A14 | workflow 未冻结；占位 runner no-op；标 PLACEHOLDER |

**Prerequisite check (gate G0):**

```bash
.venv/bin/pytest tests/packages/ai tests/packages/agent tests/capability_loader -m "not live" -q
```

P1–P3.1 离线套件须保持绿（本 plan 不回归底层）。

---

## 2. 复用的本仓能力（不重造）

| 能力 | 来源 | 用途 |
|------|------|------|
| `Agent` / `AgentHarness` / `AgentOptions` | `pi_agent.agent` / `harness.agent_harness` | 会话、prompt、abort、wait_for_idle |
| `JsonlSessionRepo` / `Session` / `DEFAULT_SESSIONS_DIR_NAME` | `pi_agent.harness.session` | JSONL 持久化 |
| `LocalFileSystem` | `pi_agent.harness.env.python_env` | `JsonlSessionRepo` 的 fs 注入（`cwd="competitive_app"`） |
| `AbortController` | `pi_agent.agent` | abort |
| `load_capability_packages` / `apply_capability_report` | `pi_agent.package_manager` | 挂 echo/search tools |
| `create_models` / `ModelsImpl` / `builtin_models` / `faux_provider` | `pi_ai` | stream_fn 注入（`models.streamSimple`）；model catalog 查询；测试用 faux |

**参考（不抄）旧仓 rr-refactor：**
- `backend/api/__init__.py` —— 路由路径 / DTO / `RuntimeRegistry` 模式（重写）
- `workflows/competitive/models.py` —— `WorkflowTaskRequest` 入参结构（粗定义）

---

## 3. 目标目录结构

```text
competitive_app/
  pyproject.toml                      # name=competitive_app; depends earendil-works-pi-agent + fastapi + uvicorn + aiosqlite
  src/competitive_app/
    __init__.py
    domain/
      __init__.py
      task.py                         # Task 值对象 + 状态机（pending/running/aborted/completed/failed）；纯
      research_brief.py               # WorkflowTaskRequest 顶层模型（research_brief/competitor_discovery 为 dict 粗定义）；纯
    application/
      __init__.py
      workflow/
        __init__.py
        session_service.py            # 建/prompt(同步)/abort(当前+排队)/get/messages；AgentHarness + JsonlSessionRepo
        task_service.py               # 建/列/取/resume/abort/delete task；占位 runner 秒翻 completed
        runtime_registry.py           # Agent 实例缓存 + per-session asyncio.Lock（排队/超时409）+ abort 取消排队
    adapter/
      __init__.py
      in/fastapi/
        __init__.py
        app.py                        # create_app + lifespan（分层失败处理 F-A23）
        routes_sessions.py            # B 组 5 路由
        routes_tasks.py               # A 组 7 路由（report stub）
        routes_health.py              # health
        dto.py                        # Pydantic v2（SessionCreateRequest 3 字段 / WorkflowTaskRequest 粗定义 / PromptRequest）
      out/persistence/
        __init__.py
        task_projection_store.py      # SQLite：tasks 表 + sessions 索引表；单连接+锁串行化写
    wiring.py                         # ModelsImpl 单例 + stream_fn + capability + repo + harness factory
  tests/competitive_app/
    contract/                         # 分层门禁 AST 扫描（O1/O2/O3）
    unit/                             # Task 状态机 / store CRUD / DTO 校验
    integration/                      # FastAPI + faux + echo 端到端（O4–O12）
    integration/live/                 # L1–L2（env-gated）
```

根 `pyproject.toml`：workspace `members` 加 `competitive_app`；root deps 加 `earendil-works-pi-agent` + `fastapi` + `uvicorn` + `aiosqlite`。

---

## 4. 状态板（update as you go）

Status: `todo` | `in_progress` | `done` | `blocked`。

| Step | Phase | Status | Note |
|------|-------|--------|------|
| G0 | P1–P3.1 离线套件绿（前置） | todo | |
| A1 | 脚手架：pyproject + 目录树 + workspace + 空 import | todo | |
| A2 | config/settings.example.yaml（capability_packages.enabled / sessions.cwd / app_db / prompt_lock_timeout） | todo | |
| B1 | domain：Task 状态机 + research_brief 顶层粗定义（纯，允许 pydantic） | todo | |
| B2 | adapter/out：SQLite store（tasks 表 + sessions 索引表，单连接+锁） | todo | |
| B3 | application/runtime_registry：Agent 缓存 + per-session Lock + abort 取消排队 | todo | |
| B4 | application/session_service：建/prompt(同步)/abort/get/messages | todo | |
| B5 | application/task_service：占位 runner 秒翻 completed + resume/abort 边界 + delete 连带 | todo | |
| B6 | wiring：ModelsImpl 单例 + stream_fn + capability + repo + harness factory | todo | |
| B7 | adapter/in：app.py + lifespan（分层失败）+ dto | todo | |
| B8 | adapter/in：routes_sessions（B 组 5） | todo | |
| B9 | adapter/in：routes_tasks（A 组 7，report stub）+ routes_health | todo | |
| C0 | 契约测试：分层门禁 AST 扫描（O1/O2/O3） | todo | |
| C1 | 单元测试：Task 状态机 / store CRUD / DTO 校验 | todo | |
| C2 | 集成测试：sessions prompt→JSONL→resume + 并发排队409 + abort（O4/O5/O8/O9/O10/O11） | todo | |
| C3 | 集成测试：tasks 占位 + resume/abort 边界 + delete 连带 + report stub（O6/O7） | todo | |
| C4 | 集成测试：启动分层失败（O12） | todo | |
| C5 | Live 测试（L1/L2，env-gated） | todo | |
| C6 | Roadmap §5 P4 → in_progress；feature/plan 状态同步 | todo | |

**Rules:**
- 不在 B4 前动 adapter/in（application 先稳）。
- 占位 runner 必须标 `PLACEHOLDER — workflow 未冻结 (Roadmap §0)`。
- 每个路由文件落地即补对应契约/集成测试。
- 不在 P4 PR 里改 `packages/ai|agent`。

---

## 5. 分阶段步骤

### Phase A — 脚手架

**A1.** 建 `competitive_app/pyproject.toml`（name `competitive_app`，depends `earendil-works-pi-agent` + `fastapi` + `uvicorn` + `aiosqlite`，python ≥3.12，hatchling）。建 §3 目录树 + 空 `__init__.py`。根 `pyproject.toml` workspace members 加 `competitive_app`，root deps 加同上。删 `competitive_app/.gitkeep`。

**A2.** `config/settings.example.yaml` 加 feature §4.5 配置（capability 白名单默认 `[echo_example]` / sessions.cwd=`competitive_app` / app_db=`data/app.db` / prompt_lock_timeout=30）。

**Exit A:** `import competitive_app` 成功；`uv sync` 通过；目录树就位。

### Phase B — 分层实现（由内向外）

**B1. domain（纯）** — `task.py`：`Task` dataclass + 状态机（pending→running→{aborted|completed|failed}，合法转移校验）。`research_brief.py`：`WorkflowTaskRequest` 顶层 Pydantic 模型（`research_brief`/`competitor_discovery` 为 `dict[str,Any]` 粗定义，`metadata: dict`；标 PLACEHOLDER）。**无** fastapi/aiosqlite/pi_agent import；允许 pydantic。

**B2. adapter/out** — `task_projection_store.py`：aiosqlite，schema = feature §5.2（`tasks` 表 + `sessions` 索引表）。单连接 + `asyncio.Lock` 串行化写（写操作锁内完整）。方法：tasks `create/get/list/update_status/delete`；sessions `index_session/get_session/delete_session`。**只存投影 + 索引**，不存对话。

**B3. application/runtime_registry** — 参考 rr-refactor `RuntimeRegistry` 重写（不抄类型）：`agents: dict[session_id, Agent]` + `locks: dict[session_id, asyncio.Lock]` + `active(task_id)/start/abort_task/shutdown`。per-session Lock：acquire 超时 `prompt_lock_timeout` 返 409。abort：`agent.abort()` + cancel 排队 Task（被 cancel 返 409）。

**B4. application/session_service** — `create_session`（建 JsonlSessionRepo session + 索引 SQLite + 建 AgentHarness）；`prompt`（acquire 锁 → `harness.agent.prompt` + `wait_for_idle` → 返回最后一条 assistant message，失败走 errorMessage）；`abort`（registry.abort：当前 + 排队）；`get`（SQLite 索引）；`messages`（session.build_context 透传）。model 解析：空→默认，非空查 catalog，查不到 422。

**B5. application/task_service** — `create_task`（建 SQLite task 记录 status=pending → 起占位 asyncio.Task 秒翻 completed → 固定返回 pending；**不建 session**）；`list/get`；`resume`（completed→返回 completed；非终态重起占位）；`abort`（边界：终态返回 aborted 不改）；`delete`（删 SQLite task + 连带删关联 session 若有）。

**B6. wiring** — `ModelsImpl` app 级单例（`create_models()` + `setProvider`，faux 测试用 `faux_provider`）；`stream_fn = models.streamSimple`；`load_capability_packages(enabled=settings...)` 一次，LoadReport 缓存；共享 `JsonlSessionRepo({"fs": LocalFileSystem(cwd="competitive_app"), "sessionsRoot": "data/sessions"})`；`TaskProjectionStore("data/app.db")`；`AgentHarness` factory（per-session，apply cached report）。

**Exit B:** application 全部可调；domain 纯；wiring 能起 harness。

### Phase C — FastAPI 入口

**B7.** `app.py`：`create_app()` + `lifespan`（建 repo/registry/加载 capability；分层失败 F-A23：缺 key 不阻断、包失败记 diagnostic、基础设施故障抛错；shutdown 释放）。CORS。`dto.py`：Pydantic v2（`SessionCreateRequest` 3 字段 / `WorkflowTaskRequest` 粗定义 / `PromptRequest`，全 `extra="forbid"`）。

**B8. routes_sessions** — B 组 5 路由，调 `session_service`。**不**直接 import pi_agent/aiosqlite。

**B9. routes_tasks + routes_health** — A 组 7 路由，调 `task_service`；`/report` 返回 `{"report": None, "note": "workflow 未冻结"}`；入参 docstring 标 PLACEHOLDER。health 返回 active_workflows 计数。

**Exit C:** 14 路由注册；`TestClient` 能打。

### Phase D — 测试与门禁

**C0. 契约测试** — `test_layout`（路径/import）、`test_deps`（分层 AST 扫描 F-A25）、`test_routes_registered`（14 路由集合 O3）。参考 `tests/packages/agent/contract/test_deps.py`。

**C1. 单元测试** — Task 状态机合法/非法转移；SQLite store CRUD（tasks + sessions 索引）；DTO 校验（model 空/非空/不存在；extra forbid）。

**C2. 集成 sessions** — `TestClient` + faux + echo：O4（prompt→200+assistant message→JSONL 落盘→messages）；O5（并发排队→超时 409）；O8（abort 在途+取消排队 409）；O9（新实例 resume）；O10（echo tool 调用）；O11（model 解析三路径）。

**C3. 集成 tasks** — O6（POST 202 pending→GET 投影 completed→report stub→sessions 空列表）；O7（resume completed→abort 边界→delete 连带删 session）。

**C4. 启动失败** — O12（缺 key 不阻断；包失败 diagnostic；基础设施故障抛错）。

**C5. Live** — L1（真 key prompt 打真网，message 非空 stopReason 合法）；L2（无 key skip）。

**C6.** Roadmap §5 P4 → `in_progress`；feature/plan 状态同步。

---

## 6. 测试策略

| 层 | 路径 | 断言 | Feature § |
|----|------|------|-----------|
| Contract | `tests/competitive_app/contract/` | 分层门禁（O1/O2）+ 路由注册（O3） | §6.1 O1–O3 |
| Unit | `tests/competitive_app/unit/` | Task 状态机；store CRUD；DTO 校验 | §6.1 |
| Integration | `tests/competitive_app/integration/` | FastAPI + faux + echo 端到端 | §6.1 O4–O12 |
| Live（可选） | `tests/competitive_app/integration/live/` | 真实 provider；`@pytest.mark.live`；无 key skip | §6.2 L1–L2 |

```bash
# offline（默认 CI）
.venv/bin/pytest tests/competitive_app -m "not live" -q
# 契约门禁（快）
.venv/bin/pytest tests/competitive_app/contract -q
# 手动起服务
.venv/bin/python -m competitive_app
```

默认 CI 无网无 key；faux + echo 覆盖主路径。Live 不 exit-blocking。

---

## 7. 风险

| Risk | Mitigation |
|------|------------|
| `JsonlSessionRepo` 无 id 索引、按 cwd 分桶 | SQLite `sessions` 索引表存 file_path+cwd（F-A5）；resume 经索引重建 |
| `AgentHarness` 只 append message，不存 model/system_prompt | SQLite 索引表存 model+system_prompt，resume 重建 harness（F-A5） |
| 单 Agent 实例不能并发 prompt（`_active_run` 抛错） | per-session Lock 排队（F-A10）；超时 409 |
| abort 撞不上排队中的请求 | registry 维护排队 Task，abort 时 cancel（F-A11） |
| 占位 task 秒翻 completed，resume/abort 成空操作 | 走边界 case 测试（F-A18）；不伪造挂起 |
| 缺 provider key 启动失败 | 分层失败：缺 key 不阻断，prompt 时 200+errorMessage（F-A23） |
| SQLite 并发写冲突 | 单连接 + asyncio.Lock 串行化写（F-A24） |
| stream_fn 胶水写错 | 参考 `scripts/smoke_live_model.py` + P2 `test_agent_harness.py`（`stream_fn=models.streamSimple`） |
| 分层门禁误报 | AST 扫描参考 `tests/packages/agent/contract/test_deps.py`；禁令白名单明确（F-A25） |
| 占位被误当真 workflow | 代码 + docstring + feature F-A14 三重标注 PLACEHOLDER |
| 环境无 uv/Python 3.12 跑不了测试 | 本 plan 不依赖本机验证；交付后由具备环境者跑 `uv run pytest` |

---

## 8. Definition of Done（本 feature 切片）

- [ ] §4 状态板 G0–C6 = `done`
- [ ] Feature §6.1 Offline O1–O12 全绿
- [ ] 分层契约测试绿（O2）
- [ ] P1–P3.1 离线套件无回归
- [ ] `competitive_app` 是唯一 app 层；底座 = `pi_agent`
- [ ] 14 路由注册并可调
- [ ] 占位 runner / report stub 均标 PLACEHOLDER
- [ ] **不**宣称真 workflow / 报告 / memory 就绪
- [ ] Roadmap §5 P4 → `in_progress`；feature `competitive-app-http-v1` frozen v0.1.1

---

## 9. 与后续 feature 的边界

```text
本 feature 交付：competitive_app DDD 骨架 + 14 路由 + JSONL/SQLite 双层 + session 索引 + 占位 runner
后续 feature：research workflow 骨架冻结 → 替换占位 runner（真跑 agent 建 session）
            → 回填 research 前置 2 接口 → report schema
            → 升 feature 至 v0.2.0+
```

本 feature 必须留稳定 `task_service` 接口，使后续 workflow feature 能替换占位实现而不改路由层。

---

## 10. 修订记录

| Version | Date | Note |
|---------|------|------|
| 0.1.0 | 2026-07-25 | 草案：P4 app 骨架 + 16 路由；参考旧仓 rr-refactor；workflow 占位 |
| 0.2.0 | 2026-07-25 | **grill 同步**：对齐 feature v0.1.1 frozen；路由 16→13；加 sessions 索引表 / per-session 锁 / abort 排队 / delete 连带 / model 解析 / 启动分层失败 / 分层禁令 / 占位不建 session；测试 O1–O12 + L1–L2 |
