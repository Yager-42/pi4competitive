# Feature 边界契约：llm-fallback-observability-v1

| 字段 | 值 |
|------|-----|
| **feature_contract_version** | `0.2.1` |
| **status** | **frozen**（grill 收敛于 2026-08-03，决策记录见 §7） |
| **updated** | 2026-08-03 |
| **feature_id** | `llm-fallback-observability-v1` |
| **roadmap_stage** | **P4** `competitive_app` —— App 层可靠性 + 可观测性边界（Multi-LLM Fallback 链 + RunJournal 事件流） |
| **architecture_contract** | [`ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.11**（§2.2 / §3.2 / §4 / D8 / D9 / D11 / D15 / D23 / D24 / D25 + §1.5） |
| **roadmap** | [`ROADMAP.md`](../ROADMAP.md) P4 |
| **参考源（非上游）** | [`HezaoHezao/poirot`](https://github.com/HezaoHezao/poirot)（MIT）—— fallback 链/journal 设计思想；[`Yager-42/ragent`](https://github.com/Yager-42/ragent)（MIT）—— 首包探测机制（`FirstPacketAwaiter`/`ProbeBufferingCallback`）。**均非父本**，非 1:1 复刻对象 |

---

## 0. 效力与状态

1. 本文是 **P4 `competitive_app` 层 Multi-LLM Fallback + Observability（RunJournal）** 的 **frozen** 功能边界（grill 收敛，决策见 §7）。
2. 标为 **locked** 的决定不得由实现者自行改写；变更须重新 grill 并升 `feature_contract_version`，并同步 Roadmap。
3. 本文**不改变架构契约**的分层、依赖方向、技术栈；唯一架构层变更 = **pi_ai 结构化错误透传**（§4.12），以 **ADR 0015** 落地（contract_version 升 0.3.12，`packages/ai` 版本 bump，ADR_SANCTIONED 契约测试更新）。其余纯 App 层，不触发 ADR。
4. **禁止引入 LangChain/LangGraph**（契约 §2.2；§6 LLM 仅 `packages/ai` + `packages/agent`）——poirot 代码中依赖 `langchain_core`/`langgraph` 的部分一律**不搬**，只平移设计。
5. 对外业务事件继续脱敏（契约 §4）：journal payload 不得泄漏密钥/隐私（§4.9）。
6. 本文不改变已冻结 HTTP 契约（`competitive-app-http-v1`）；`task_spans`/SSE 消费语义保持。

---

## 1. 动机与目标（locked grill）

### 1.1 问题

| 现状 | 缺口 |
|------|------|
| `packages/ai` `retry_async`：指数退避重试（max_retries=2），**同模型** | 无跨 provider 降级；限流/5xx/超时只能干等同一家 |
| `wiring.py::_ModelResolver`：单模型解析；`stream_fn = models.streamSimple` 单点注入 | 无降级链、无兜底 provider |
| pi_ai 错误模型：httpx 异常**不抛**，吞进事件流（`stopReason="error"` + `errorMessage` 文本） | 降级判定无结构化错误可用；文本匹配脆弱 |
| 观测三套并存：session JSONL（SoT）+ SQLite `task_spans` + SSE 业务事件 | 无统一 run 级结构化事件流；LLM 失败/降级、tool 输入输出无完整序列可回放 |

### 1.2 目标（locked）

1. **Multi-LLM Fallback（App 层）**：全局单降级链（`LLM_FALLBACK_PROVIDERS` env，逗号分隔）+ **首包探测**（ragent 机制）+ **全程缓冲、批式交付** + `_active` provider 记忆。思想抄 poirot 链式降级 + ragent 首包探测，调用语义落在 pi `ModelsImpl.streamSimple` 之上（`stream_fn` 包装）。
2. **pi_ai 结构化错误透传（ADR 0015）**：`AssistantMessage` 加 `error` 结构化字段，fallback 判定基于字段而非文本。
3. **Observability（App 层）**：`RunEvent`/`RunJournal` 数据层**原样抄** poirot；埋点分两层：harness 生命周期事件经 JournalBridge（extension 事件面）落 journal；task 业务事件经 `_make_emit` **统一三写出口**（span→SQLite、SSE→queue、journal→文件）。
4. `events.jsonl`（`data/runs/<task_id>/`）成为 run 级完整事件流；run_id = task_id（1:1）。

### 1.3 非目标（locked grill）

| 不做 | 说明 |
|------|------|
| 角色化路由（`MODEL_ROUTES`/researcher/reporter/reflection） | grill G4 否决：全局单链 `LLM_FALLBACK_PROVIDERS` |
| 改 `packages/agent`（中间件、journal 埋进 harness） | D3/D8；埋点只经现有 extension 事件面 |
| 引入 LangChain/LangGraph 任何代码 | 契约 §2.2 |
| 抄 poirot `RunJournalMiddleware`/`build_chat_model`/`bind_tools` | LangGraph 专属/框架面，不搬 |
| 抄 ragent Java 代码 | 仅机制思想：等待器 + 缓冲回调 + 超时取消 |
| 跨 run 聚合仪表盘 / 事件查询 API | 已有 `dashboard_stats`；本 feature 只交付事件写入 |
| 改已冻结 HTTP 路由（SSE/trace）语义 | 只追加事件源，不重定义消费端 |
| 模型/密钥入 git | D23：密钥仅 env |
| 流式实时交付（批式） | grill G7c：全程缓冲批式交付，下游非实时（agent 循环语义不受影响） |

---

## 2. 规范源与角色（locked grill）

| 来源 | 角色 | 约束 |
|------|------|------|
| poirot `config/fallback_model.py` | fallback 链**逻辑结构源**（轮转循环 / `_active` 记忆 / 全链失败抛最后错误） | 结构平移；判定源换成结构化 error 字段（§4.2）；LangChain 面不搬 |
| ragent `FirstPacketAwaiter` / `ProbeBufferingCallback` / `RoutingLLMService` | **首包探测机制源** | 只搬思想：等待器（成功/错误/超时/无内容状态）+ 缓冲回调（探测期缓存、成功后回放）+ 超时取消；不搬 Java 代码 |
| poirot `config/model_router.py` + `provider_config.py`（`route_chain_for`/`discover_available_providers`） | 路由构造**思想源** | 角色概念不搬（G4）；enabled+key 发现逻辑保留；`build_chat_model` 不搬 |
| poirot `journal/events.py` + `run_journal.py` | journal 数据层**直接源** | **原样抄**（MIT；纯标准库） |
| 本仓 `packages/ai` `ModelsImpl` / `streamSimple` / `AssistantMessage` | **模型层底座 SoT** | 只加 ADR 0015 的结构化 error 字段；其余只读使用 |
| 本仓 `packages/agent` extension 事件面（`extensions/types.py` 白名单） | **埋点事件面 SoT** | 事件名已存在，勿新增平行钩子（P3.1 规则） |
| 本仓 `competitive_app` `wiring.py` / `task_service.py` / `_HarnessFactory` | **组合根与生命周期 SoT** | chain 构造、journal 生命周期、统一 emit 出口在此接线 |
| 本仓 `.env` | **配置面**（D23） | 链配置/开关/超时全部 env |

---

## 3. 落点与模块映射（locked grill）

### 3.1 目录落点

```text
packages/ai/src/earendil_works/pi_ai/     # ADR 0015 变更（仅 error 字段）
  types.py                                  #   AssistantMessage + error: NotRequired[ErrorInfo]
  api/_http_stream.py                       #   error_message() 填结构化 error 字段
competitive_app/
  application/model/                      # 新增：fallback（组合在 wiring）
    router.py                               #   FallbackRouter：LLM_FALLBACK_PROVIDERS 解析 + 链构造 + 发现
    fallback_stream.py                      #   FallbackStream：首包探测 + 全程缓冲 + 轮转 + _active
  application/workflow/
    journal_bridge.py                       # 新增：extension 事件 → journal.append（白名单过滤 + 脱敏）
  adapter/out/observability/              # 新增：journal 文件 IO（out adapter）
    events.py                               #   RunEvent（原样抄 poirot）
    run_journal.py                          #   RunJournal（原样抄 poirot）
  wiring.py                               # 组装：chain → FallbackStream；journal 注入；_make_emit 三写
data/runs/<task_id>/events.jsonl          # D25 数据面；随 task 删除级联
.env                                      # LLM_FALLBACK_PROVIDERS / LLM_FALLBACK_FIRST_PACKET_MS / LLM_FALLBACK_DISABLED
docs/contracts/adr/0015-pi-ai-structured-error.md   # 新增 ADR
```

不新增第三方依赖（httpx/openai 已是 pi_ai 依赖；journal 纯标准库）。

### 3.2 映射表 A：Multi-LLM Fallback

| 源（poirot / ragent） | 抄法 | 本仓落点 | 适配 |
|---|---|---|---|
| poirot `FallbackChatModel` 轮转循环 + `_active` | 结构原样 | `application/model/fallback_stream.py` | `for offset in range(n): idx=(active+offset)%n` 原样；调用面 `models[idx].invoke()` → 首包探测消费 `streamSimple(model=chain[idx], ...)`；`bind_tools` 删 |
| poirot `_should_fallback` 白名单 | 思想原样、判定源替换 | 同上 | 判定源 = 结构化 `error` 字段（`type`/`statusCode`）：timeout/connection/http_error(429,5xx) → 降级；http_error(400/401/403/404) → 不降级；`import openai` 分支删 |
| ragent `FirstPacketAwaiter` | 思想原样 | 同上 | pi 版：等待流内首个实质事件（text_start/toolcall_start/done）或 error 事件，超时 `LLM_FALLBACK_FIRST_PACKET_MS`（默认 60000）；结果态 success/error/timeout/no_content |
| ragent `ProbeBufferingCallback` | 思想原样 | 同上 | pi 版：缓冲全部事件 → done/error 后一次性交付（G7c 批式）；无"commit 即实时"路径；失败丢弃缓冲切下家 |
| ragent 超时取消 | 思想原样 | 同上 | `streamSimple(..., signal=abort_signal)` 取消当前流再切下家 |
| poirot `route_chain_for`/`discover_available_providers` | 逻辑保留、角色删除 | `application/model/router.py` | 输入 `LLM_FALLBACK_PROVIDERS`（逗号分隔，默认单元素=主模型）；按序筛 enabled+有 key 的 provider；`LLM_FALLBACK_DISABLED=1` → 链=主模型直通 |
| poirot `build_chat_model` | 不抄 | wiring.py | → `create_models()` + `setProvider(provider_factory())`；chain = list[Model dict]（`getModels(provider)` 或复用 `_ModelResolver` 合成） |

**关键简化**：单 `ModelsImpl` 注册链上所有 provider，`chain = list[Model dict]`（`streamSimple` 按 dict 的 `provider` 字段路由）；`_active` 记链下标，语义与 poirot 一致。**无角色概念**（G4）：全局一条链。

### 3.3 映射表 B：Observability

| 源 / 机制 | 抄法 | 本仓落点 | 适配 |
|---|---|---|---|
| poirot `journal/events.py::RunEvent` | 原样 100% | `adapter/out/observability/events.py` | 零依赖 dataclass |
| poirot `journal/run_journal.py::RunJournal` | 原样 100% | `adapter/out/observability/run_journal.py` | `append`/`_make_event_id`/JSONL 格式原样 |
| poirot `RunJournalMiddleware` 埋点事件名 | 事件名参考 | 两层出口（下） | 机制不搬（LangGraph） |
| poirot `run_manager.create_run` 建 journal | 结构原样 | `task_service._run_research` 入口 | run_id = task_id；`data/runs/<task_id>/events.jsonl`；task 删除级联删 run 目录 |

**埋点两层出口**（locked）：

1. **harness 生命周期层**（JournalBridge，App 侧薄 extension，订阅现有 extension 事件 → journal.append）：
   - `agent_start` / `agent_settled` → journal `agent.started` / `agent.finished`
   - `before_provider_request` / `after_provider_response` → `llm.request` / `llm.response`（payload 带 model）
   - `tool_call` / `tool_result` → `tool.called` / `tool.finished`（tool 输出截 2000 字符）
   - `session_before_compact` + `prepare_compaction` 结果 → `compaction.*`
   - `getContextUsage()` 调用点 → `budget`

2. **task 业务层**（`task_service._make_emit` 升级为**统一三写出口**，G6）：
   - `span` 事件 → SQLite `task_spans` + journal（`trace.span`）+ 不入 SSE（现状保持）
   - 11 个业务事件 → SSE queue + journal（`task.*`）
   - 直连 append：`skill.select`/`skill.apply`（capability report 应用处）、`help.requested`/`help.exhausted`（workflow 失败路径）、`report.generated`（report 完成）、`llm.fallback_*`（FallbackStream 内部事件）

**事件白名单**（§4.10）：journal 只接受下表事件类型，未知类型拒绝并告警：

| 事件类型 | 来源 |
|---|---|
| `agent.started` / `agent.finished` | JournalBridge |
| `llm.request` / `llm.response` / `llm.fallback_start` / `llm.fallback_switch` / `llm.fallback_exhausted` | JournalBridge / FallbackStream |
| `tool.called` / `tool.finished` | JournalBridge |
| `compaction.*` | JournalBridge |
| `budget` | 直连 |
| `skill.select` / `skill.apply` | 直连 |
| `help.requested` / `help.exhausted` | 直连 |
| `report.generated` | 直连 |
| `trace.span` | 统一出口 |
| `task.*`（11 业务事件原样透传） | 统一出口 |

---

## 4. 边界决策（locked grill）

- **B1 落点**：fallback = `application/model/`（组合在 wiring）；journal = `adapter/out/observability/`（文件 IO 属 out adapter）。D9 组合在 wiring、Domain 无 IO。
- **B2 错误判定面**：结构化 `error` 字段（G2a），**不用文本匹配**。分类规则：`type ∈ {timeout, connection}` 或 `type == http_error 且 statusCode ∈ {429} ∪ [500,600)` → 降级；`type == http_error 且 statusCode ∈ {400,401,403,404}` → 不降级，原样透出。
- **B3 配置面**：全部 env（`.env`，D23）。`LLM_FALLBACK_PROVIDERS`（逗号分隔，按序降级；默认未设 = 主模型单元素直通）；`LLM_FALLBACK_FIRST_PACKET_MS`（默认 60000）；`LLM_FALLBACK_DISABLED=1`（调试开关，链=主模型直通）。无 settings.yaml 配置面。
- **B4 journal 生命周期**：`task_service._run_research` 入口创建（run_id = task_id）；task 结束/中止 flush；文件 `data/runs/<task_id>/events.jsonl`；task 删除级联删 run 目录（复用现有 delete 逻辑）。
- **B5 统一 emit 出口**（G6）：`_make_emit` 升级为三写（span→SQLite、SSE→queue、journal→文件）；SSE 现有 11 业务事件语义不变；span 不入 SSE（现状保持）。
- **B6 降级判定**（G7/G7a/G7c）：首包探测 + **全程缓冲批式交付**——FallbackStream 消费当前 provider 流，缓冲全部事件；首个实质事件（text_start/toolcall_start/done）前出现 error 事件或超时（`LLM_FALLBACK_FIRST_PACKET_MS`）→ 取消（signal）切下家；首包成功但最终 done 前 error → **也切下家重放**（缓冲未交付，无脏数据）；done → 一次性交付缓冲。`_active` 链下标记忆；全链失败返回最后一个 error 消息（B7）。
- **B7 错误暴露**：全链失败与客户端错误均以 pi 原语义透出（`stopReason="error"` + 结构化 `error`），**不抛异常**——保持与现有 harness/调用方行为一致。
- **B8 降级开关**（G14）：`LLM_FALLBACK_DISABLED=1` → FallbackStream 直通主模型（无探测无缓冲，纯透传）。
- **B9 脱敏**（G9 黑名单）：密钥/凭据/Authorization 头永不落 journal；tool 输出截 2000 字符；`before_provider_headers` 事件**不**落 journal；其余透传。
- **B10 事件白名单**（G10）：journal 只接受 §3.3 白名单事件类型；未知类型拒绝 + 告警（`logger.warning`），不落盘。
- **B11 首包超时**（G7b）：`LLM_FALLBACK_FIRST_PACKET_MS` 默认 60000ms，env 可覆盖；单测注入短值。
- **B12 pi_ai 变更（ADR 0015）**：`AssistantMessage` 加 `error: NotRequired[ErrorInfo]`（`{statusCode?: int, type: Literal["timeout","connection","http_error","parse","aborted","other"], message: str}`），仅 `stopReason=="error"` 时存在；`errorMessage` 文本保留（向后兼容，session SoT 历史数据不受影响）。`_http_stream.error_message()` 填充。contract_version 0.3.11 → 0.3.12；`packages/ai` 版本 bump；ADR_SANCTIONED 契约测试补 3 条（error 字段形状/仅 error 时存在/类型枚举）。
- **B13 测试范围**（G12）：**两层**——Offline（unit：每接口正常功能 + 鲁棒性双用例；faux 集成全链路）默认全跑；Live（`@pytest.mark.live` + `live_env` fixture 门控，`.env` 缺 key 即 skip）：真实 provider 链路——降级切换（坏 key provider → 自动切真 provider → `_active` 记忆）与 journal 事件落盘。live 纪律：只证链路跑通，结果正确性归 offline 断言。

---

## 5. 关键适配 delta（实现须知）

1. **无 LangChain**：`FallbackChatModel(BaseChatModel)` → `FallbackStream`（纯 async 包装 `stream_fn`，实现 pi `AssistantMessageEventStream` 兼容接口——harness 无感）。
2. **无异常抛出**：判定走结构化 `error` 字段（ADR 0015），非 `except` 分类。
3. **批式交付**：FallbackStream 内部消费真实流并缓冲；对 harness 暴露的流在 done/error 后一次性重放——接口保持 `AssistantMessageEventStream` 形态（async iterator + `result()`）。
4. **首包探测**：等待器等待首实质事件（text_start/toolcall_start/done）或 error 事件，超时走 `asyncio.wait_for` 语义 + signal 取消当前 provider 流。
5. **单 ModelsImpl 多 provider**：chain 是 Model dict 列表；`_active` 语义不变；并发 task 各自持有独立 FallbackStream（per-harness），无共享可变状态。
6. **`bind_tools` 删除**：pi `streamSimple(tools=...)` 已支持。
7. **中间件 → JournalBridge**：LangGraph `AgentMiddleware` 钩子映射为 extension 事件（§3.3），用现有 `create_extension_runtime()` 挂载（参考 `_HarnessFactory.build_ephemeral` 现有做法）。
8. **统一 emit 出口**：`_make_emit` 三写时保持事件对象不变（SSE 消费者零感知）；journal 写入失败**不阻断** runner（try/except + 告警，与现状 span 记录同款容错）。

---

## 6. 验收标准（locked）

1. **Fallback 单测**（对照 poirot `test_fallback_model.py` + ragent 探测语义平移）：
   - 链轮转：首 provider 429 → 第二成功；`_active` 更新；下次调用从上次成功 provider 起试；
   - 客户端错误（400/401/404）不降级，原样透出；
   - 首包超时（注入短 `LLM_FALLBACK_FIRST_PACKET_MS`）→ 切下家；
   - 首包成功后中途 error → 切下家重放，下游只收到完整交付（无半截）；
   - 全链失败 → 返回最后一个 provider 的 error 消息；
   - `LLM_FALLBACK_DISABLED=1` → 直通（无探测无缓冲）；
   - 单 provider 链退化为直通（无降级无损耗）。
2. **ADR 0015 契约测试**：`AssistantMessage.error` 形状；仅 `stopReason=="error"` 时存在；`type` 枚举合法；`errorMessage` 兼容保留。
3. **Journal 单测**（对照 poirot `test_run_journal.py`）：append → 文件含完整事件 dict；追加语义；非法事件类型拒绝。
4. **集成**：一次 `_run_research` 全流程后 `events.jsonl` 含 `agent.started` → `llm.request/response`（×N）→ `tool.called/finished` → `agent.finished` 完整序列；`task.*`/`trace.span` 经统一出口三写（SQLite/SSE/journal 各就位）；task 删除级联删 run 目录。
5. **回归**：现有测试全绿（含 contract-drift）；`packages/agent` 零 diff；`packages/ai` 仅 ADR 0015 变更。
6. **Live 验收**（`@pytest.mark.live` 门控，无 key skip 不阻塞）：链 = [坏 key provider, 真 key provider] → 真实 LLM 调用成功且 journal 含 `llm.fallback_start`/`llm.fallback_switch`，`_active` 记忆生效（下一轮无再降级）；真实 LLM 调用一轮 → `events.jsonl` 含 `llm.request`/`llm.response`（payload.model 正确）。

---

## 7. Grill 决策记录（locked）

| # | 决策点 | 结论 |
|---|--------|------|
| G1 | 落点 | `application/model` + wiring 组合 |
| G2 | 错误判定面 | **改 pi_ai 透传结构化错误**（ADR 0015，动 packages/ai） |
| G2a | 错误字段形状 | `AssistantMessage.error: NotRequired[ErrorInfo]`（statusCode?/type/message），与 errorMessage 并存 |
| G3 | 配置面 | **env**（.env 已有模型配置；无 settings.yaml 面） |
| G4 | 路由链形状 | **单一 `LLM_FALLBACK_PROVIDERS`**（逗号分隔，全局单链；**否决**角色化 MODEL_ROUTES） |
| G5 | run_id 语义 | run_id = task_id（1:1），随 task 删除级联 |
| G6 | 与现状共存 | **一步到位统一 emit 出口**（span→SQLite、SSE→queue、journal→文件三写） |
| G7 | 降级判定机制 | **首包探测**（ragent `FirstPacketAwaiter`/`ProbeBufferingCallback` 思想） |
| G7a | 首包后失败 | **也降级重放**（全程缓冲保证无脏数据） |
| G7b | 首包超时 | 60s 默认 + env `LLM_FALLBACK_FIRST_PACKET_MS` 覆盖 |
| G7c | 缓冲边界 | **全程缓冲批式交付**（下游非实时；agent 循环语义不受影响） |
| G8 | 全链失败暴露 | 返回 error 消息（pi 语义，不抛异常） |
| G9 | 脱敏 | 黑名单（密钥/凭据/头不落）+ tool 输出截 2000 |
| G10 | 事件白名单 | 白名单 + 拒绝未知（告警） |
| G11 | journal 位置 | `data/runs/<task_id>/events.jsonl` |
| G12 | 测试范围 | **两层**：Offline（unit 正常+鲁棒 + faux 集成，CI 全跑）+ Live（`@pytest.mark.live` 门控真实链路，缺 key skip） |
| G13 | 文档拆分 | 合一份（当前） |
| G14 | 降级开关 | `LLM_FALLBACK_DISABLED=1` |

---

## 8. 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.1.0 | 2026-08-03 | draft 初稿：落点 + 模块映射 + 边界决策 + grill 清单（G1–G14） |
| 0.2.0 | 2026-08-03 | **frozen**：grill 收敛。关键变更——G2 改 pi_ai（ADR 0015）；G4 否决角色路由改全局单链；G7 首包探测（ragent）+ G7a/G7c 全程缓冲批式交付 + 首包后也降级重放；G6 统一三写 emit 出口；G3/G14 env 配置面；§4 全部锁定 |
| 0.2.1 | 2026-08-03 | **测试两层化 patch**：B13/G12 从"单测 + faux，无 live"改为 Offline（unit 正常功能 + 鲁棒性双用例 + faux 集成）/ Live（真实链路降级切换 + journal 事件，门控）两层；§6 加 Live 验收条目；live 纪律：只证链路跑通，结果正确性归 offline |
