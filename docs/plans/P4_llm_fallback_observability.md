# Plan: P4 — `competitive_app` Multi-LLM Fallback + Observability（RunJournal）

| Field | Value |
|-------|--------|
| **plan_version** | `0.1.5` |
| **status** | **completed**（v0.1.5 勘误，实现不变） |
| **created** | 2026-08-03 |
| **updated** | 2026-08-03 |
| **roadmap** | [`docs/ROADMAP.md`](../ROADMAP.md) stage **P4** `competitive_app` |
| **feature** | [`docs/features/llm_fallback_observability_v1.md`](../features/llm_fallback_observability_v1.md) **v0.2.1 frozen** — `llm-fallback-observability-v1`（G1–G14 / B1–B13） |
| **ADR** | [0015 pi-ai structured error](../contracts/adr/0015-pi-ai-structured-error.md)（阶段 1） |
| **depends_on** | **P4 `competitive_app` HTTP + research-workflow done**（wiring / task_service / _HarnessFactory 现役） |
| **reference** | poirot `config/fallback_model.py` + `journal/`（MIT，设计/数据层抄源）；ragent `FirstPacketAwaiter`/`ProbeBufferingCallback`（首包探测思想） |
| **target** | `competitive_app/application/model/` + `competitive_app/adapter/out/observability/` + `competitive_app/application/workflow/journal_bridge.py` + `packages/ai`（仅 ADR 0015） |
| **tests** | `tests/competitive_app/unit/test_fallback_stream.py`、`test_fallback_router.py`、`test_run_journal.py`、`test_journal_bridge.py`、`test_journal_stream.py` + `tests/packages/ai/unit/test_http_stream_error.py`（或现有单测文件内） |
| **non_goal** | 角色化路由（G4 否决）；LangChain/LangGraph；跨 run 聚合 API；改已冻结 HTTP 路由语义；`packages/agent` 任何改动 |

---

## 0. Purpose

1. App 层引入 **Multi-LLM Fallback**：全局单降级链（`LLM_FALLBACK_PROVIDERS` env）+ 首包探测 + 全程缓冲批式交付（ragent 机制，poirot 链思想，pi `stream_fn` 语义），`_active` provider 记忆。
2. App 层引入 **RunJournal**：`RunEvent`/`RunJournal` 原样抄 poirot（MIT），统一 run 级事件流（`data/runs/<task_id>/events.jsonl`），埋点两层（JournalBridge extension 事件 + `_make_emit` 统一三写）。
3. **ADR 0015**：pi_ai `AssistantMessage.error` 结构化错误字段（唯一 packages 改动），fallback 判定输入。

**Approach（COPY 纪律）:** **COPY 为主，ADAPT 为点**。契约 §1.6 规则（"能映射即 COPY-semantics，确有 Python/host interface delta 才 ADAPT"，P3.3 移植先例）对本文**全部抄源文件生效**：凡可 COPY 处**逐字搬**（含注释/格式，仅 import 路径调整），一律不重写；确需 ADAPT 的点必须在 §2 每文件的 **ADAPT 点清单**中显式列出（框架面/接口面，无可避免才 ADAPT），清单外的任何"顺手改写"= 违规。三个抄源中：poirot journal 数据层 **COPY 100%**；poirot fallback 链 **COPY 骨架 + 点状 ADAPT**（清单见阶段 3）；ragent 为 Java，**只思想平移**（语言面，无代码可 COPY）。

**Non-goals of this plan:**

| Out of scope | Why |
|--------------|-----|
| 角色化路由 MODEL_ROUTES | grill G4 否决：全局单链 |
| `packages/agent` 任何改动 | D3/D8；埋点只经现有 extension 事件面 |
| LangChain / LangGraph | 契约 §2.2 |
| 跨 run 聚合 / 事件查询 API | 已有 dashboard_stats |
| SSE/trace 路由语义变更 | 已冻结 HTTP 契约 |
| settings.yaml 配置面 | grill G3：全部 env |

---

## 1. Binding constraints (contract for implementers)

| ID | Must |
|----|------|
| Feature v0.2.1 | G1–G14 / B1–B13 — **no inventing open scope** |
| ADR 0015 | `AssistantMessage.error` NotRequired；仅 `stopReason=="error"`；`errorMessage` 保留；产点仅 `_http_stream.error_message()` |
| D15 / D4 | `packages/ai` 除 ADR 0015 外零改动；`packages/agent` 零改动 |
| §2.2 / §6 | 无 LangChain/LangGraph；LLM 仅 pi_ai/pi_agent |
| D9 | Domain 无 IO；组合在 wiring |
| D23 | 配置仅 env（`.env`）；密钥不入 git |
| D24 / D25 | session SoT 不变；journal 落 `data/runs/` |
| G6 / B5 | `_make_emit` 三写：SSE 消费者零感知（事件对象不变）；span 仍不入 SSE |
| B6 / B8 | 全程缓冲批式交付；`LLM_FALLBACK_DISABLED=1` 直通 |
| B9 / B10 | 脱敏黑名单 + 事件白名单拒绝未知 |
| P3.1 规则 | 不新增平行 extension 事件名（用现有白名单） |
| COPY 纪律 | 每个抄源文件头加 **transplant 标注**（source 仓库/SHA/license，仓库先例：`sandbox_provider.py` transplant 头 + POIROT-MIT.txt）；COPY 100% 文件保留 poirot 原文注释；ADAPT 点必须落 §2 清单，超出清单的改动 = 违规 |

---

## 2. 实施阶段（串行，按依赖序）

### 阶段 1 — ADR 0015：pi_ai 结构化错误（packages/ai 唯一变更）

| 文件 | 变更 |
|------|------|
| `packages/ai/src/earendil_works/pi_ai/types.py` | 加 `ErrorInfo` TypedDict（`statusCode: NotRequired[int]` / `type: Literal["timeout","connection","http_error","parse","aborted","other"]` / `message: str`）；`AssistantMessage.error: NotRequired[ErrorInfo]` |
| `packages/ai/src/earendil_works/pi_ai/api/_http_stream.py` | `error_message()` 加分类逻辑：HTTP ≥400 → `http_error`+statusCode；httpx `TimeoutException`/`ConnectError`/`ReadError` → `timeout`/`connection`/`other`；aborted → `aborted`；`errorMessage` 文本保留同源 |
| `packages/ai/pyproject.toml` + `__init__.py` | 0.81.2 → **0.81.3** |
| `tests/packages/ai/unit/` | error 分类单测（400/401/403/404/429/5xx/timeout/connection/aborted；成功无 error；errorMessage 兼容） |
| `tests/test_deps.py` | `ADR_SANCTIONED` 补 packages/ai 文件（types.py、api/_http_stream.py） |
| 契约 | `ARCHITECTURE_CONTRACT.md` 0.3.11 → **0.3.12**（决策摘要 D*/ADR 列表 + 变更记录行） |

**验收**：单测绿；ADR_SANCTIONED 通过；其余 packages/ai 测试零回归。
### 阶段 2 — journal 数据层（**COPY 100%**，零依赖）

| 文件 | 来源 |
| `competitive_app/adapter/out/observability/events.py` | poirot `journal/events.py` **逐字 COPY**（`RunEvent` frozen dataclass + `to_dict()` + `utc_now_iso()`；含 `_CST` 时区语义）；仅 import 路径调整 + 文件头 transplant 标注 |
| `competitive_app/adapter/out/observability/run_journal.py` | poirot `journal/run_journal.py` **逐字 COPY**（`RunJournal.append()` + `_make_event_id()` + JSONL 追加格式 `json.dumps(..., indent=2) + "\n\n"`）；同上 |
| `competitive_app/adapter/out/observability/__init__.py` | 导出（新建，非抄） |
| `tests/competitive_app/unit/test_run_journal.py` | poirot `test_run_journal.py`（26 行）**整搬**：仅 import 路径换 `competitive_app.adapter.out.observability`；断言逐字保留 |

**验收**：单测绿；文件格式与 poirot 逐字节兼容（字段序一致）。

### 阶段 3 — FallbackRouter + FallbackStream（fallback 核心）

| 文件 | 抄法 | COPY / ADAPT |
|------|------|-------------|
| `competitive_app/application/model/fallback_stream.py` | poirot `fallback_model.py` **骨架逐行 COPY**：`for offset in range(n): idx=(active+offset)%n` 轮转、`_active` 记忆、全链失败抛最后错误的控制流与注释**原样保留**。**ADAPT 点清单（仅 4 处）**：①调用面 `self.models[idx].invoke(...)` → pi 事件流消费（首包探测 + 全程缓冲，ragent 思想）；②错误判定 `except → _should_fallback(exc)` → 读 `error` 字段（ADR 0015），分类表照抄（timeout/connection/429/5xx → 降级；400/401/403/404 → 不降级）；③`bind_tools` 删除（pi streamSimple 自带 tools）；④全链失败 `raise last_exc` → 返回最后 error 消息（G8/B7，pi 语义不抛异常）。首包探测为 G7 新增语义，叠加在 ① 内（`asyncio.wait_for` + signal 取消；`LLM_FALLBACK_FIRST_PACKET_MS` 默认 60000） | COPY 骨架 + 4 ADAPT |
| `competitive_app/application/model/router.py` | poirot `provider_config.py` **COPY**：`ProviderConfig` frozen dataclass / `ProviderConfigError` / `discover_available_providers`（enabled+key 判定 + priority 排序）逐字搬；`route_chain_for` 的"空链/兜底追加"结构保留但**输入换成 env 链**（G4 否决角色表，`LLM_FALLBACK_PROVIDERS` 逗号分隔，未设 → `[主模型]`）；**ADAPT 点**：①`build_chat_model`（LangChain 构造）→ pi `create_models`+`setProvider` 映射（框架面）；②`provider_profile` 表 → pi provider 工厂注册表 | COPY + 2 ADAPT |
| `competitive_app/application/model/__init__.py` | 导出（新建，非抄） | — |
| `tests/competitive_app/unit/test_fallback_stream.py` + `test_fallback_router.py` | poirot `test_model_router.py` **行为断言语义照抄**：`test_fallback_on_transient_error`（`_active` 记忆）/`test_client_error_propagates_without_fallback`/`test_all_failures_raises_last`/`test_should_fallback_*` 逐一平移；**ADAPT**：`FakeListChatModel`（LangChain 测试替身）→ pi scripted 事件流替身；判定断言从异常改 `error` 字段 | 语义 COPY + 替身 ADAPT |
**验收**：单测全绿；harness 通过 `stream_fn=fallback_stream` 注入后无感（接口兼容）。

### 阶段 4 — JournalBridge（harness 生命周期埋点）

| 文件 | 抄法 | COPY / ADAPT |
|------|------|-------------|
| `competitive_app/application/workflow/journal_bridge.py` | **重写**（poirot `RunJournalMiddleware` 是 LangGraph `AgentMiddleware` 子类，机制面不可 COPY——契约 §2.2 禁 LangGraph）。**行为对齐项**（从 poirot 中间件抄语义）：事件命名（`agent.*`/`llm.*`/`tool.*`）、tool 输出截 2000、无 journal 时静默不报错；映射到现有 extension 事件（feature §3.3 表）；白名单过滤（B10）+ 脱敏黑名单（B9） | 机制重写 + 行为语义 COPY |
| `tests/competitive_app/unit/test_journal_bridge.py` | 新写（本仓无对应源）；断言对齐 feature §6.3 语义 | 新写 |

**验收**：单测绿；与阶段 3 的 FallbackStream 事件（`llm.fallback_start/switch/exhausted`）合并白名单。

### 阶段 5 — 统一 emit 出口 + wiring 组装（App 接线）

| 文件 | 变更 |
|------|------|
| `competitive_app/application/workflow/task_service.py` | `_make_emit` 升级三写：`span` → SQLite `task_spans` + journal（`trace.span`）；11 业务事件 → SSE queue + journal（`task.*`）；journal 写入失败 try/except 不阻断 runner；`_run_research` 入口创建 journal（run_id=task_id，`data/runs/<task_id>/events.jsonl`），结束/中止 flush；task 删除级联删 run 目录（现有 delete 逻辑扩展） |
| `competitive_app/wiring.py` | 组装：`create_models()` + 链上各 provider `setProvider()`；`FallbackRouter.build_chain()` → `FallbackStream` 包装 stream_fn（`LLM_FALLBACK_DISABLED=1` 直通）；journal 注入 harness/runner |
| `competitive_app/application/model/journal_stream.py` | **host delta（v0.1.3 补注）**：本 port 的 `agent_loop.py` 不调用 `config.onPayload`/`onResponse`（上游 TS 有，Python port 未接）→ `before_provider_request`/`after_provider_response` extension 事件永不触发。`llm.request`/`llm.response` 改由 **JournalStream**（StreamFn 兼容包装，stream_fn 单点）产出：调用入口写 `llm.request`（model/provider），流终态（done/error）写 `llm.response`（status ok/error + errorType）；事件透传；lazy setup 同 `_FallbackCall`。JournalBridge 的 `before_provider_request` 处理器保留（上游补钩子后可直接接）。judge 的 `completeSimple` 不经 stream_fn → 无 `llm.*`（其 `trace.span` 已覆盖） |
| `competitive_app/application/workflow/coverage_engine.py` + `extraction.py` | 直连 append 点：`help.requested`/`help.exhausted`（失败路径）、`skill.select`/`skill.apply`（capability 应用处）、`report.generated`（report 完成）、`budget`（getContextUsage 调用点） |
| `.env.example`（仓库根） | 新增 `LLM_FALLBACK_PROVIDERS` / `LLM_FALLBACK_FIRST_PACKET_MS` / `LLM_FALLBACK_DISABLED` / `RUNS_ROOT` 注释项 |

**验收**：一次 `_run_research` 后 `events.jsonl` 含完整序列（feature §6.4）；SSE 消费者零回归（事件对象不变）。

### 阶段 6 — 集成 + 回归

| 项 | 内容 |
|----|------|
| 集成测试（offline） | faux 全流程：`events.jsonl` 序列断言（agent.started → llm.request/response ×N → tool.called/finished → agent.finished + task.*/trace.span 三写就位）；task 删除级联删 run 目录 |
| Live 测试 | §3.2 两条（`test_live_fallback_switch` / `test_live_journal_llm_events`），`.env` 有 key 时跑通；无 key 自动 skip |
| 回归 | 现有测试全绿（含 contract-drift `test_deps.py`）；`packages/agent` 零 diff；`packages/ai` 仅 ADR 0015 diff |
| 文档同步 | AGENTS.md 表格补 feature/ADR/plan 行；ROADMAP §5 阶段标志（若 P4 有标志位） |
**验收**：§6 验收标准（feature）全条目通过。

---

## 3. 测试清单（两层：Offline 全跑 / Live 门控）

### 3.1 Offline 层（无真实 key，CI 默认全跑）

**Unit —— 每个接口的正常功能 + 鲁棒性**（两类用例都必须，缺一不可）：

| 接口/模块 | 正常功能（功能正确） | 鲁棒性（异常/边界/并发） |
|-----------|----------------------|--------------------------|
| ADR 0015 error 分类（tests/packages/ai/unit/） | 各状态码（400/401/403/404/429/5xx）与 httpx 异常（timeout/connection）→ `error.type`/`statusCode` 映射正确 | 未知异常 → `other`；成功消息**无** `error` 字段；`errorMessage` 文本兼容保留 |
| RunJournal（test_run_journal.py） | append 落盘、事件字段完整（event_id/run_id/event_type/payload/created_at）、追加语义 | 目录不存在自动建；多事件连续追加；白名单拒绝未知事件类型（B10） |
| FallbackRouter（test_fallback_router.py） | env 解析（逗号分隔）、链构造、无 key provider 过滤、优先级排序 | 未设 `LLM_FALLBACK_PROVIDERS`（→ 单元素直通）；空链；未知 provider 名；`LLM_FALLBACK_DISABLED=1` 开关 |
| FallbackStream（test_fallback_stream.py） | 链轮转、`_active` 记忆（下次从上次成功起试）、客户端错误（400/401/404）不降级、全链失败返回最后 error、单链直通 | 首包超时（注入短 `LLM_FALLBACK_FIRST_PACKET_MS`）→ 切下家；首包成功后中途 error → 切下家重放且下游无半截；signal 取消当前流；并发实例独立（无共享 `_active`） |
| JournalBridge（test_journal_bridge.py） | extension 事件 → journal 事件序列映射正确（feature §3.3 表） | 白名单拒绝未知事件；脱敏（密钥/凭据/Authorization 头不落）；tool 输出截 2000；无 journal 时静默不报错 |

**Faux 集成（全链路，无真实 key）**：faux provider 跑通一次 `_run_research` → harness + FallbackStream + JournalBridge + `_make_emit` 三写（SQLite/SSE/journal 各就位）→ `events.jsonl` 完整序列断言（agent.started → llm.request/response ×N → tool.called/finished → agent.finished + task.*/trace.span）→ task 删除级联删 run 目录。

### 3.2 Live 层（真实链路跑通，`@pytest.mark.live` + `live_env` fixture 门控，`.env` 缺 key 即 skip）

复用 `tests/live_env.py`（`live_credentials`/`live_openai_model`）与 `tests/competitive_app/integration/live/conftest.py` 现有惯例：

| 测试 | 验证的真实链路 |
|------|----------------|
| `test_live_fallback_switch` | 链 = [首包必败 provider, 真 key provider] → 首包失败自动切 → 真实 LLM 成功返回 → journal 含 `llm.fallback_start`/`llm.fallback_switch`；`_active` 记忆生效（下一轮直接从好 provider 起，无再降级）。注（v0.1.5 勘误）：坏 key=401 按 B2 **不降级**，故"首包必败"实现为**死 endpoint**（connection 错误；系统代理环境下呈现为 5xx，仍属可降级） |
| `test_live_journal_llm_events` | 真实 LLM 调用一轮 → `events.jsonl` 含 `llm.request`/`llm.response`（payload.model = 实际 model id）+ 事件时间序正确 |
| 全流程（可选增强，不 gate 本 feature） | 一次真实 research task 完成后 events.jsonl 全序列 + task_spans 三写；无 key 环境跳过不阻塞 |

**live 测试纪律**：不测降级后的"结果正确性"（那是 offline 断言的事）；live 只证明**链路跑得通**（真实 provider 调用 → 失败识别 → 切换 → journal 事件落盘）。

## 4. 风险

| 风险 | 缓解 |
|------|------|
| `AssistantMessageEventStream` 兼容接口实现偏差导致 harness 无感失败 | 阶段 3 先做接口兼容单测（faux harness 注入 FallbackStream 跑一轮） |
| 首包探测 + 批式交付改变 LLM 调用实时性（SSE 业务事件不受影响，assistant 消息批式） | feature G7c 已接受；集成测试断言事件序列完整 |
| `_make_emit` 三写回归 SSE | 事件对象原样复用（同一 dict 引用三写），集成测试断言 SSE 队列内容不变 |
| poirot 抄入代码许可/来源标注 | 文件头注释标注 source（仓库已有先例：sandbox contract transplant 头 + POIROT-MIT.txt） |
| **COPY 纪律执行**：实现者"顺手重写"抄源文件（超出 ADAPT 清单）引入偏移 | §1 COPY 纪律约束 + 阶段验收逐文件 diff 核对（抄源文件 diff 只允许 import 路径/ADAPT 点/transplant 头三类差异） |

---

## 5. 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.1.0 | 2026-08-03 | 初稿：6 阶段（ADR 0015 → journal 数据层 → fallback → JournalBridge → 统一出口 → 集成回归） |
| 0.1.1 | 2026-08-03 | **COPY 纪律强化**：§0/§1 加 COPY 为主 + ADAPT 点清单机制（契约 §1.6 规则）；阶段 2 标 COPY 100%（含测试整搬）；阶段 3 逐文件列 COPY/ADAPT 等级与 ADAPT 点清单（fallback_stream 3 点 / router 2 点）；阶段 4 JournalBridge 明示"机制重写 + 行为语义 COPY"；§4 加 COPY 纪律执行风险与 diff 核对验收 |
| 0.1.2 | 2026-08-03 | **测试两层化**：§3 重写为 Offline（unit 正常+鲁棒 双用例 + faux 集成）/ Live（`@pytest.mark.live` 门控，真实链路降级切换 + journal 事件）两层；阶段 6 加 live 验收条目；live 纪律（只证链路跑通，结果正确性归 offline） |
| 0.1.3 | 2026-08-03 | **实现补注（host delta）**：阶段 5 补 `journal_stream.py` 行——本 port agent loop 无 onPayload/onResponse 钩子，`llm.request`/`llm.response` 产点 = JournalStream（stream_fn 单点），JournalBridge 对应处理器保留待上游钩子；fallback 链按 feature §3.2 原样使用（无链修正） |
| 0.1.4 | 2026-08-03 | **completed**：六阶段全部落地并验证——ADR 0015（pi_ai 0.81.3 / contract 0.3.12）；journal 数据层 COPY poirot 100%；FallbackRouter/FallbackStream（首包探测 + 全程缓冲 + `_active`）；JournalBridge + JournalStream（llm.* 产点，host delta）；wiring 三写 + runs 生命周期 + delete 级联；faux 集成 + live 2 条（真实降级切换 + journal 事件）全绿；全量 580 passed / 0 failed（含预存在 P3.3-era live 测试修复 2 处：L4 `evolution_cycle_runner` 引用、live env 裸 `os.environ` 残留污染）；`packages/agent` 零 diff |
| 0.1.5 | 2026-08-03 | **收尾核对勘误（实现零改动）**：§1 约束 Feature v0.2.0 → **v0.2.1**；阶段 3 fallback_stream ADAPT 清单 3 处 → **4 处**（补④全链失败 `raise last_exc` → 返回 error 消息 G8/B7，与文件头声明一致）；阶段 5 `.env.example` 路径（config/ → 仓库根）+ 补 `RUNS_ROOT` 项；header tests 字段补 `test_journal_stream.py`；§3.2 `test_live_fallback_switch` 措辞勘误（坏 key=401 按 B2 不降级，"首包必败"实现为死 endpoint）。COPY diff 核对通过：journal 两文件仅 import/头注释差异；fallback_stream/router 骨架与 poirot 逐行同构 |