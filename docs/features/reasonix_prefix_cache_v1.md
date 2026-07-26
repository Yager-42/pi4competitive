# Feature 边界契约：reasonix-prefix-cache-v1

| 字段 | 值 |
|------|-----|
| **feature_contract_version** | `0.1.0` |
| **status** | **frozen** |
| **updated** | 2026-07-26 |
| **feature_id** | `reasonix-prefix-cache-v1` |
| **roadmap_stage** | **P3.2** — Pi extension capability enablement（ADR 0009；P3.1 baseline done） |
| **architecture_contract** | [`ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.5** |
| **depends_on** | ADR 0009；[`agent_engine_extensions_v1.md`](agent_engine_extensions_v1.md) P3.1 baseline **v0.2.2 frozen** + 实现前版本化 P3.2 delta |
| **roadmap** | [`ROADMAP.md`](../ROADMAP.md) |
| **plan** | [`docs/plans/P3_2_pi_extension_capability_enablement.md`](../plans/P3_2_pi_extension_capability_enablement.md) |
| **path** | `docs/features/reasonix_prefix_cache_v1.md` |
| **交付形态** | 本地 capability package（`capability_packages/…`）+ **通用 host `CompactionPlan` transaction**（**G1-R / G1-P**）；Reasonix 业务策略不得焊入核心 |
| **参考（非 SoT）** | Reasonix 不变量；商城 `pi-reasonix` / `pi-deepseek-cache` / `pi-cache-optimizer` / `pi-better-messages-cache` 仅参考 |
| **明确无关** | 旧仓 competitive-agent 缓存；`@realvendex/pi-cache` runtime memo |

---

## 0. 效力与状态

1. 本文是 **Reasonix 式前缀 / KV 缓存纪律** 的 **frozen** 边界契约。标 **locked** 的决定不得由实现者自行改写。
2. 变更 locked 行须重新 grill 并升 `feature_contract_version`，同步 plan / roadmap。
3. **禁止** 在 P3.2 plan 门禁未绿时宣称本 feature 已完成；P3.1 钩子运行时已具备，本 feature 是 **消费者 + 纪律 + 最小 enablement**，不是再造 extension 子系统。
4. 架构 / 本地 package / extension 事件名仍以架构契约 + ADR 0006/0008/**0009** + `agent_engine_extensions_v1` 为最高约束；冲突 → **先 ADR 或升 extension feature**。
5. **不做** 第二 agent 内核、整仓 Reasonix 替换、TUI、npm install 路径。

---

## 1. 动机与目标

### 1.1 问题

Provider 侧 prompt/prefix cache（DeepSeek 等）要求 **请求前缀字节稳定**：system、tools schema 序、早期 fewshots、历史 rewrite 策略一旦抖动 → cache miss 成本上升。

本仓已有：

- `packages/ai`：`cacheRead` / `cacheWrite`、`CacheRetention`、部分 provider header 碎片；
- P3.1：`before_agent_start` / `context` / `before_provider_request` / compact / tool 事件等 **IN** emit。

**缺失：** 以 capability package 表达的 **前缀纪律**（ImmutablePrefix + AppendOnlyLog）与 **命中率可观测**。

### 1.2 目标（v1）

1. 在 **不 fork 第二内核** 的前提下，用 extension + **通用 host compaction bridge**（Q5b）落地 Reasonix 式前缀缓存纪律。
2. Session 内可证明：**前缀稳定**（A）+ **实际的低频历史 rewrite 唯一口**（B）+ **usage 指标**（E）；B 不再以 H0「尽力观测」伪装完成。
3. 交付以本地 `capability_packages/<name>/` 为消费者；核心若需改动，只能提供 provider-neutral 的 bridge / apply 能力，**不得**内嵌 Reasonix prefix policy、tool repair、成本策略或第二 loop。

### 1.3 非目标（v1）

见 §2 OUT 表。另：不做完整 Reasonix 产品、不做商城包 npm 依赖、不做 competitive-agent 缓存移植。

---

## 2. v1 柱选择（locked grill — Q1）

| 代号 | 柱 | v1 | 含义 |
|------|----|----|------|
| **A** | **ImmutablePrefix** | **IN** | session 内钉死 system + **排序/冻结的 tools schema** + fewshots；fingerprint；中途变更 tool 集合 → **显式接受** cache miss（可诊断，不静默假装命中） |
| **B** | **AppendOnlyLog** | **IN** | 对话历史对 provider 路径**只 append**；`compact` 是唯一 rewrite 口；plan / transaction / mechanical fallback 可复现，**LLM summary 可变且每次 rewrite 重建 epoch** |
| **C** | VolatileScratch | **OUT** | 临时态不上游；v1 不做 |
| **D** | 辅件（tool-call repair / 大 tool_result 收缩 / flash-first 成本柱） | **OUT** | v1 不做 |
| **E** | **指标** | **IN** | 可观测真实 `cacheRead` / `cacheWrite`（及衍生 hit-rate）与 `expected_cold` 解释；不伪造 provider `cacheMiss` |
| **F** | Runtime tool memo（`@realvendex/pi-cache` 类） | **OUT** | 与前缀正交；禁止混进本 feature |

**定案一句话：** v1 = **A + B + E**；**C/D/F OUT**。

### 2.0 最小桥接纪律（locked grill — Q8）

后续未决选择一律按以下优先级裁决：

1. 既有 Pi extension event / Context 足以交付 A+B+E 时，直接使用；不得另造 host hook 或 abstraction。
2. 仅当既有面无法诚实交付已锁能力时，允许一个**最小、generic、无 Reasonix policy** 的 host bridge；B 的 CompactionPlan transaction 是已证实的例外。
3. 不移植 Reasonix 完整 host/product 子系统（boot、CLI/TUI、environment probe、跨重启 cache store）；这些不是 extension 接入的必要条件。

**定案一句话：** 尽量 port Reasonix 的缓存不变量，而不是复制其完整运行时；最短既有 Pi 路径优先。

### 2.1 纪律落点（Q2 **superseded** by Q5a/B1）

原 Q2 的 **H0** 曾选择纯 extension、零内核 diff。经核验现有 `AgentHarness.compact()` 只生成/emit result 而未在该路径实际 rewrite Agent/session，且 `ExtensionContext.compact()` 当前显式不可用；因此 H0 无法诚实满足 Q1 的 B。

| 原决定 | 状态 | 影响 |
|--------|------|------|
| **H0**（纯 extension / 零内核 diff） | **superseded** | 不再是 v1 实现前提；保留为决策历史 |
| **B1**（B 是硬要求） | **locked** | 必须允许最小 host bridge 进行真实 compaction / rewrite；具体通用 API、re-entry、summary 责任见 **Q5b** |

**硬边界仍有效：** capability package 拥有 Reasonix policy；host 只提供 generic compaction primitive / apply path。若 Q5b 证明公开 extension 面或分层需变，先重开 `agent_engine_extensions_v1`，再由 Q11R 判断 ADR / 架构契约影响。

> **不可再声称：** 本 feature 对 `packages/agent` 零行为影响。B1 的目的正是让 B 真实发生；但它不授权把 Reasonix 业务写进 Agent core。

### 2.2 事件映射（locked grill — Q3）：**M-core+**

本包的普通 handler 遵循 P3.1 runner 的已加载 extension 顺序；**Q21 locked（Q21c–f superseded；Q21g/h 保留）：** 不新增 runner `priority` / `final` phase，也不暴露 order/position 的公开 hook（ADR 0009 D-P32-3）。v1 能力集在 ADR 0006 下是**闭合、全一方（first-party）**的：search / echo 仅 `registerTool`，**Reasonix 是唯一改 payload 的 extension**，故它**按构造即 terminal** —— 无论加载顺序都观测到实际 outbound payload。因此**不引入有序 `enabled` load plan 机器**；`enabled` 保持无序 whitelist（或"加载全部合法子目录"）。若未来新增任何也改 payload 的一方包，它**必须组装在 Reasonix 之前**，并由 ADR 0009 D-P32-4(4) 已要求的 Reasonix+search 同载组合门禁验证 Reasonix 仍为唯一/末位 payload mutator。Pi 式 reload / runner replacement 被允许；新 attached runtime 若含 Reasonix，以其首个 canonical outbound payload 建立独立 epoch，旧 fingerprint 与 metrics 不跨 runner 聚合。fingerprint 是本包 handler 点的**观测值**且仅供诊断，E 指标恒取真实 `message_end` usage 而与加载顺序无关。

| 分类 | 事件 | v1 本包职责 | 返回 / 变更边界 |
|------|------|-------------|-----------------|
| **A 必选** | `before_provider_request` | 取得 adapter 将发送的 payload；建立/比较实际 system/tools/request prefix fingerprint | **P1** canonicalize 已知 tools 形状；Q7 钉支持 provider；未知形状 identity return + 诊断 |
| **B 必选** | `session_before_compact` | 唯一可由本包提供 deterministic `compactionPlan` 或 `cancel` 的协作口 | Q5 决定 compaction 生成方式；禁止把它扩展成通用 history rewrite API |
| **E 必选** | `after_provider_response` | 记录 HTTP `status` / `headers`，用于 provider / header 型 cache 诊断 | 当前 event **不含** token usage；只观测 |
| **E 必选** | `message_end` | 只读最终 assistant `message["usage"]` 的 `cacheRead` / `cacheWrite` 等 | handler **MUST** 返回 `None`；不得替换 finalized message |
| **B 必选（T2）** | `turn_end` | 读取 generic `ctx.getContextUsage()`；仅在阈值满足时请求 `ctx.compact()` | handler **MUST** 返回 `None`；不得 summary、rewrite、处理 tool 或绕过 C1 |
| 推荐 | `session_start` | 初始化本包 session epoch / 指标状态 | 只写包内状态 |
| 推荐 | `context` | 只读检查 provider 前的 messages 是否与先前 append 轨迹连续 | handler 默认返回 `None`；不作为 v1 rewrite 口 |
| 推荐 | `session_compact` | 记录 compact 后 checkpoint / epoch | 只写包内状态 |
| 明确不订 | `tool_*` / `turn_start` / `message_start` / `message_update` / 其他 IN | 除 T2 所需的唯一 `turn_end` 外，D 已 OUT；v1 不引入 tool repair、回合末直接收缩或无关观测噪音 | 不注册 |

**已核验的运行时事实：**

1. `after_provider_response` 来自 `StreamOptions.onResponse`，现有 HTTP adapter payload 为 `{status, headers}`；是否某特定 provider adapter 调用它由 **Q7** 约束。
2. `cacheRead/cacheWrite` 位于最终 assistant message 的 `usage`，故 E **必须**订 `message_end`；仅订 response event 不满足 Q1 的 E。
3. `before_provider_request` 通过 `StreamOptions.onPayload` 到 provider adapter；不支持的 payload 形状不可在本包内假装 canonicalized。

**定案一句话：** `M-core+` = 三个原必选事件 + **只读 `message_end`** + T2 的唯一 `turn_end`；推荐三事件；`before_agent_start` 不订。

### 2.3 工具 schema canonicalization（locked grill — Q4a）：**P1**

本包在 `before_provider_request` 中对 **已支持**的 provider payload 做 active canonicalization；排序后的对象就是实际交给 adapter 的请求对象，而非仅供 hash 的影子副本。

| 形状 | canonicalization |
|------|------------------|
| OpenAI-compatible | `payload["tools"]` 按 `tool["function"]["name"]` 升序排序；若 V1 adapter 已在 tool 上放置唯一 `cache_control`，携带该**同一值**到排序后最后一个 tool |
| Anthropic Messages | `payload["tools"]` 的 immediate / `defer_loading` 两组各按 `tool["name"]` 升序；immediate 始终在 deferred 前。若 V1 adapter 已在 immediate tool 上放置唯一 `cache_control`，携带该**同一值**到排序后最后一个 immediate tool |
| 其他 / 形状不完整 | **不变更** payload；记录 `unsupported_tool_shape` diagnostic；不得伪称 canonicalized |

**精确规则（locked）：**

1. 工具名使用稳定字符串升序；同名工具视为 loader collision policy 已处理的异常输入，不以本包「猜一个赢家」。
2. 仅递归稳定 **mapping 的 key 顺序**（包括 JSON Schema object）；**保留所有 schema array 原序**，如 `required`、`enum`、`oneOf` / `anyOf`，因为 array 序可能具语义。
3. 仅排序 provider **tools 定义数组**；不得重排 messages、tool call、tool result 或其它 payload list。
4. Anthropic `defer_loading` 是 adapter 的语义分区：只在各分区内排序，且保持 immediate 在 deferred 前；当前未带该字段的 Python payload 视为单一 immediate 分区。
5. P1 绝不选择 retention / control 值。仅当 V1 adapter 已选定且 tool 数组恰有一个可识别的 tool-level `cache_control` 时，P1 可在排序后将该**原值**转移到上述 adapter-defined cache boundary；不得新增、删除、改写值或移动 system / history 上的 marker。
6. marker 数量不为一、marker 位于不合法分区、或形状未知 / 不完整时，**不变更整个 payload**并记录 `unsupported_tool_cache_marker_shape` diagnostic；不得伪称 canonicalized。
7. 不改 `Agent.state.tools`、`AgentTool` 定义或执行映射；模型仍按 tool name 调用原 tool。
8. fingerprint 在 canonicalization **之后**计算，并对应实际发出的 canonical request 表示。

**定案一句话：** A 的「排序」在 package 的已知 provider payload 上实现；未知 provider 退化为诊断，不冒充稳定前缀。

### 2.4 Prefix epoch（locked grill — Q4b）：**E1 rebase**

1. 本包在**首个受支持 provider 的、已 P1 canonicalize 后**的实际 payload 上建立 `epoch=0` baseline；不得在 package load / `session_start` 时猜测尚未经 adapter 变换的工具表示。
2. 本包分别跟踪 immutable-prefix 成分（system、canonical tools、Q8 定义的 fewshot）与 append-only log；正常追加消息本身**不**构成 `prefix_break`。
3. immutable-prefix 成分发生真实变化时：
   - 记录一次 `prefix_break`（前后 fingerprint、原因、epoch）；
   - 标记本次为 `expected_cold`，含义仅为「旧前缀不可继续复用」；**不得**把它称作已证实的 provider `cache_miss`；
   - 仍发送请求，并以变更后的 canonical prefix 建立 `epoch=N+1` baseline。
4. 在新 epoch 内稳定的后续请求恢复为可观察的 cache 候选；真实 `cacheRead/cacheWrite` 仍由 E（Q9）判定。
5. 不拒绝请求、不回滚 tools、不写 Agent state；这些均与 H0 冲突。模型/provider cache namespace 的分段规则由 Q7 钉死。

**定案一句话：** 新 tool/schema/system/fewshot 是**一次显式 prefix break + 新 epoch**，不是永久违规，也不是未经证实的 cache miss。

### 2.5 B 的真实性（locked grill — Q5a）：**B1**

**定案：** AppendOnlyLog / compact 不是观察标签。v1 要有一个真实、低频、可诊断的 rewrite path；compact 是该 path 的唯一正当入口，完成后产生新的 cache epoch。

**Reasonix 对照（已核验）：** 原版在正常回合 append-only；先做 deterministic tool-result snip/prune；必要时使用无 tools 的 executor provider 生成 fold，并 `Session.Rewrite(...)`；失败时才用 deterministic mechanical fallback。它把每次 rewrite 当明确 cache-reset point，而不是承诺模型摘要字节 deterministic。

**本仓边界：** B1 只锁「需要真实 host bridge + rewrite」；**Q5b 已锁 G1-R/G1-P**（包完整计划、host 事务），**Q5c 已锁 S1**（当前 provider 的无-tools summary、有限 retry、deterministic fallback）。

### 2.6 Compaction bridge（locked grill — Q5b）：**G1-R / G1-P**

**分层定案：** 以 Reasonix 的**行为**为目标，但不把 Reasonix 业务写入 `packages/agent`。

```text
reasonix capability package
  → 构造 CompactionPlan（Reasonix policy）
  → 请求 generic host transaction
  → 接收 result / 记录新 epoch

packages/agent generic transaction
  → 校验 CompactionPlan
  → 使用当前 Agent provider 做无-tools summary（Q5c）
  → 一次性 apply history/session rewrite
  → 更新 rewrite version、emit、re-entry guard
```

| 层 | 允许职责 | 禁止职责 |
|----|----------|----------|
| Reasonix package | trigger / 阈值；fold/keep/tail 分区；summary 指令；prefix/epoch 诊断 | 读取 key；直接调用 provider；直接写 Agent/session；复制 host 原子事务 |
| Generic host | 验证 plan；保持 tool-call/result 配对；无-tools provider summary；原子 apply；version / emit / re-entry | `Reasonix` 命名；DeepSeek 专属策略；阈值、摘要业务 prompt、tool repair、D 类 shrink 策略 |

`CompactionPlan` **必须**足以表达 Reasonix B 的消息分区，不能退化为仅一条 summary instruction；其精确字段/validation/re-entry 规则归 Q2R，summary 语义归 Q5c。

**`pi-reasonix` 限定参考：** 可借其 Pi payload / usage adapter；其源码没有真实 session rewrite，且每请求 tool-result truncation 属 D OUT，**不得**作为 B 的实现范本。

**定案一句话：** G1-R 追求与 Reasonix 等价的 B 行为；差别只在**策略在 package、事务在 generic host**，而非缓存结果能力较弱。

### 2.7 完整 B 优先级（locked grill — Q5d）

**定案：** v1 以完整 **A+B+E** 为交付目标；允许为此在 `packages/agent` 补齐**通用** host `CompactionPlan` transaction。Reasonix policy 仍只存在于 capability package。

这改变已 frozen P3.1 的未接线 `compact()` 行为和实现计划，**不**改变既有依赖方向、local-only 边界或「extension 是 context/payload 改写唯一公共路径」的架构分层。Q2R 继续钉最小 public surface；Q11R 在该 surface 明确后判断 ADR / architecture contract version 是否需要变更。

**定案一句话：** 「Pi 零实现改动」不优先于真实 B；「Reasonix 不进入核心」仍是硬边界。

### 2.8 Summary 执行（locked grill — Q5c）：**S1**

1. host 用**当前 Agent 的 provider / model 配置**执行 summary，**不传 tools**；摘要业务 instructions 由 `CompactionPlan` 的 package policy 提供。
2. 沿用当前 Agent 的 temperature；单次 deadline 为 **90 秒**；仅非 deadline 失败重试**一次**。
3. 两次失败或 deadline 后，host 写入 deterministic mechanical digest，仍完成经验证的原子 rewrite；必须记录 `summary_mode=mechanical_fallback` 与失败原因。
4. LLM summary **不承诺字节确定性**。无论是 LLM summary 还是 mechanical fallback，只有 rewrite 成功后才建立新 epoch；禁止把模型输出差异误报为 provider cache miss。
5. Offline 测试以 injected deterministic stream 验证 plan、retry、rewrite 和 fallback；不得要求真实 provider 对同一输入返回同字节 summary。
6. summary 是 host-internal isolated simple completion：它复用当前 Agent 的非 extension 通用 transport resolution（model、key resolver、静态 headers、temperature 与 generic cache retention），但必须剥离 Agent `session_id` 与 tools。不得进入 Agent loop，也不得触发任何 extension callback（包括 `before_provider_headers`、`before_provider_request`、`after_provider_response`、`message_end`）；summary usage 只能写 compaction entry / test trace，不得建立或改变 E1 prefix baseline、cache bucket 或 session metrics。

**定案一句话：** 目标是稳定的 append-only epochs 与明确 rewrite reset，不是虚假的 LLM-output determinism。

### 2.8a Auto-compaction trigger（locked grill — Q14）：**T2**

1. Reasonix package 在每个 `turn_end` 读取 generic `ctx.getContextUsage()`；P3.2 harness binding 必须按 upstream Pi 语义提供“最近 provider usage + trailing context estimate”的 token 视图。
2. 对有效 `tokens` 与正数 `model.contextWindow`，触发条件严格为 `tokens > contextWindow - 16_384`。满足时 package 只调用 `ctx.compact()` 登记请求；C1 checkpoint 才执行 transaction。
3. package plan 的保留尾部默认约 `20_000` tokens，并只能选 P1 的完整有效边界。`16_384` reserve 与 `20_000` keep-tail 对齐既有 Python harness / upstream Pi compaction defaults。
4. usage 或 context window 缺失 / 无效则不 rewrite、不中断请求，只记录 `context_usage_unavailable` diagnostic。无 Reasonix JSON/YAML / env tuning surface。

**定案一句话：** 用已有 Pi 的固定保守阈值触发 package-owned compaction policy；host 只负责通用 usage / transaction 路径。

### 2.8b Small-context adaptive safety（locked grill — Q15 / Q15a）：**W2 / W2a**

1. 当 `contextWindow >= 36_384` 时，严格使用 T2：`reserve=16_384`、`keepTail=20_000`。
2. 当 `0 < contextWindow < 36_384` 时，Reasonix package 的有效 policy 为：`effectiveReserve = min(16_384, ceil(0.20 * contextWindow))`，`effectiveKeepTail = min(20_000, floor(0.50 * contextWindow))`，触发条件仍为 `tokens > contextWindow - effectiveReserve`。
3. S1 的 summary 请求最大输出为 `floor(0.80 * effectiveReserve)`；因此 adaptive 分配至少留下 30% context window 给 summary / 后续余量，而不把全部窗口拿去 retain。
4. `contextWindow` 无效、usage 无法获得、或 P1 无法选择至少一个有效 fold boundary 时，fail-safe：不登记 transaction、不 rewrite、不循环重试；只记录相应 diagnostic。该数值 policy 是 Reasonix package 内部默认值，不新增 config/env。

**定案一句话：** 长窗口完全沿用 Pi 默认；小窗口按可测试的 20% reserve / 50% tail 比例自适应，并在无法安全 fold 时停止。


### 2.8c Summary determinism boundary（locked grill — Q16）：**D1**

1. Reasonix 同构的可复现边界是 package plan 的选择 / 分区、host validation / transaction、以及 mechanical fallback template；同一 snapshot、policy 与 failure classification 必须得到相同的 non-LLM rewrite 决定。
2. S1 的正常 LLM summary **不承诺字节一致**，也不要求 seed / temperature 幻想性地证明确定性；provider 输出不同不是错误。
3. 每次成功 rewrite（LLM 或 mechanical）都建立新 epoch。旧 prefix cache 不再被主张可复用，因此 summary 字节差异不得被记录为 cache miss 或 prefix break。
4. Offline 测试必须断言 LLM path 的 plan、rewrite、epoch 和保留边界；只对 mechanical fallback 的同输入 / 同 failure classification 断言字节一致。

**定案一句话：** 对齐 Reasonix：让 compaction transaction 可证明，而不是要求 LLM 成为伪确定性函数。

### 2.8d Durable continuation content（locked grill — Q18/Q20）：**K1 + K2-R**

1. System 仍在 P1 candidates 外保持原样；active-turn 与 T2/W2a 所选 recent tail 必须 retain。
2. package 必须 verbatim retain：每个用户 entry（仅当其估算 token `<= min(1_500, 0.15 * contextWindow)`）以及所有先前 compaction summary entry / message。任一过大的用户输入可 fold，避免其独占 context window。
3. 除上述 retain 集之外，其余历史只可按完整 assistant tool-call / tool-result 边界 fold；被 fold 的用户信息必须交由固定 summary instructions 传递，不能以删除替代摘要。
4. package-owned instructions 的固定 headings 为：`Standing facts & constraints`、`Goal`、`Decisions & rationale`、`Important outcomes`、`Open questions & next step`。内容用简短条目，保留标识符 / 数字 / 用户硬约束；不得猜测，不得加入 Files、Commands、workspace 或 coding-agent 专用栏目。
5. 旧 summary 永不被下一次 LLM summary 再次 fold；这样用户已形成的 contract 与摘要不会在多轮 compaction 中漂移丢失。

**定案一句话：** 对齐 Reasonix：每个小型用户意图与旧摘要逐字保留，折叠其余工作；但使用基础 Agent 的通用 continuation briefing。

### 2.8e Auto-compaction stuck guard（derived from Reasonix）：**L1**

1. L1 只约束 T2/W2a 发起的 automatic compaction；不新增 package config，显式 manual host compact 不计入该 guard。
2. package 在本进程的 session state 中维护 `consecutiveAutoRewrites` 与 `autoCompactPaused`。只有其 pending automatic request 导致实际 committed rewrite（`session_compact`）才递增；无 plan、validation failure、cancel 或未提交 transaction 均不计数。
3. 后续有效 `turn_end` 一旦 `tokens <= contextWindow - effectiveReserve`，必须清零计数并解除 pause。第二次连续 automatic rewrite 提交后必须 pause；在再次降至阈值以下前，后续 over-threshold turn 不得再调用 `ctx.compact()`。
4. 这避免保留集本身已超过安全余量时逐回合 rewrite / epoch churn；不新增 UI、tool、host diagnostics API 或 outgoing event。Offline gate 必须覆盖：过小窗口至多两次连续 auto rewrite，健康窗口不误 pause，回落后可恢复。

**定案一句话：** 重复 rewrite 不会修复过小窗口；暂停自动压缩比持续打碎 warm prefix 更安全。

### 2.9 CompactionPlan 承载面（locked grill — Q2R-a）：**R1**

1. `ctx.compact()` 只请求 host 进入 compaction lifecycle；它**不**接收完整 plan。
2. Reasonix package 在既有 `session_before_compact` handler 中，基于 host 提供的 immutable preparation 返回 typed `compactionPlan`；它不得返回 package 自产的最终 `CompactionResult`。
3. host 读取 `compactionPlan` 后验证 snapshot 身份、完整消息分区、tool-call/result 原子边界与 re-entry 条件；验证成功才执行 §2.8 的 S1 summary、写 compaction entry、同步 Agent state 并 emit `session_compact`。
4. 这是 `SessionBeforeCompactResult` 的 generic host-delta variant；不新造 Reasonix hook，不把完整计划暴露为 Context action，也不破坏既有 `compaction?: CompactionResult` 的上游兼容语义。

**定案一句话：** package 在已有 lifecycle event 中描述「压什么、保留什么、如何摘要」；host 是唯一能实际压缩的执行者。

### 2.10 CompactionPlan 身份与分区（locked grill — Q2R-b）：**P1**

1. host 给 `session_before_compact` 的 preparation 是 immutable entry snapshot，带 `snapshotFingerprint`、按原序的 candidate `entryId`、受保护的 active-turn `entryId` 和只读消息投影。
2. `CompactionPlan` 至少包含 `version`、匹配的 `snapshotFingerprint`、按原序的 `foldEntryIds`、`retainEntryIds`、package-owned `summaryInstructions`、JSON-safe `details`。
3. host 要求每个 candidate entry **恰好**属于 fold 或 retain；两个列表不得重复、乱序、引用 snapshot 外 entry 或携带 message copy。所有 active-turn entry 必须 retain。
4. host 从自己的 snapshot 取 summary 输入与 `retainedTail`，验证每个 assistant tool-call 与关联 tool-result 同属 fold 或 retain；失败只出 diagnostic，不 rewrite。

**定案一句话：** package 可选择 entry，不能携带、伪造或改写 entry 内容。

### 2.11 In-loop checkpoint（derived from Reasonix + Pi loop — Q2R-c）：**C1**

1. Reasonix 的语义是「消息已写入后、下一 provider request 前」；本仓的等价点是 private host `prepareNextTurn` checkpoint：它在 `turn_end` 后运行，并可替换 agent loop 的 authoritative `current_context`。
2. `ctx.compact()` 在已绑定的 `AgentHarness` 中只同步登记一个 request（`accepted` / `already_pending`）；bare `Agent` 仍显式抛未接线错误。它不得在 extension handler 内 await summary 或直接 rewrite。
3. checkpoint 串行执行：emit `session_before_compact` → R1/P1 validation → S1 summary/fallback → append compaction entry → 由 Session 重建 context → 同步 `Agent.state.messages` 与 loop `current_context` → emit `session_compact`，然后才允许下一 provider request。
4. 每 session 同时至多一个 transaction；re-entry 合并为一个 pending request。transaction 中 snapshot 改变、plan 无效或取消时不写 rewrite；summary 失败按 §2.8 fallback 后提交。Reasonix package 依 §2.8e **L1** 处理 threshold / stuck policy。

**定案一句话：** 不是“agent 完全结束后再压”，而是在同一 loop 的安全 checkpoint 完成一次串行 rewrite。

### 2.12 Compaction handler collision（derived from Reasonix single-writer invariant — Q2R-d）：**X1**

1. `cancel` 保持上游短路语义：任何 handler 返回 cancel 即停止后续 handler，且不产生 rewrite。
2. `compactionPlan` 的所有权必须唯一：恰好一个 plan 才可进入 P1 validation；零个 plan 走原有 host default path / no-op。
3. 两个或更多 plan，或 plan 与 legacy `compaction?: CompactionResult` 同时出现，均记录 load/runtime diagnostic，且 fail-closed：不 summary、不写 compaction entry、不 rewrite。
4. 纯 legacy `compaction?: CompactionResult` 的多 handler last-nonempty-result 行为维持 upstream；X1 只约束新增的 generic plan 变体。

**定案一句话：** summary instructions 可组合；历史 rewrite plan 不可组合，也不可由包加载顺序静默决定。

### 2.13 治理结论（derived from ADR 0008 + ADR 0009 — Q11R）

R1/P1/C1/X1 的**分层本身**不新建 package 或依赖方向：仍使用既有 `compact()`、`session_before_compact` / `session_compact` lifecycle 与 private `prepareNextTurn` checkpoint，不新造平行 public hook。

但 **Q10 的 S2** 已将这项受限 Pi enablement 明确列为 P3.2，改变了 D16 的阶段顺序；因此 **ADR 0009 + architecture contract v0.3.5 已必需且已落盘**。这不是把 Reasonix policy 写进 core，而是为其 generic bridge / upstream parity 建立受控阶段。

实施前仍必须：

1. 将 `agent_engine_extensions_v1` 升到下一 feature-contract version，明载 `CompactionPlan` variant、C1 binding、C1/P1/X1 的拒绝语义；
2. 为 `P3_1_agent_engine_extensions` 增加版本化 P3.2 plan delta 和对应测试门禁；
3. 保持 ADR 0006/0008 的 local-only、S-engine、无 TUI / 无平行 hook 边界，并让 P3.2 feature / plan 通过其 exit gate。

**定案一句话：** bridge 的职责边界仍是既有 extension 架构；P3.2 的新阶段顺序通过 ADR 0009 显式治理，不能再声称“无 ADR / 无 architecture bump”。

### 2.14 Provider capability registry（locked grill — Q7）：**V1**

v1 的 active cache transport 按**已验证 API family + model compat**，不按泛化的 provider 名猜测：

| Adapter family | Active 行为 | 真实证据 |
|---|---|---|
| OpenAI-compatible（含 DeepSeek） | 按 upstream Pi 语义传 `prompt_cache_key` / supported retention；规范化 nested `prompt_tokens_details.cached_tokens`、DeepSeek top-level `prompt_cache_hit/miss_tokens` 与可用 write tokens | 最终 assistant `usage.cacheRead/cacheWrite` |
| Anthropic Messages | 按 upstream Pi compat 写 `cache_control`（system、history、supported tools）及 retention；解析 `cache_read_input_tokens` / `cache_creation_input_tokens` | 最终 assistant `usage.cacheRead/cacheWrite` / `cacheWrite1h` |
| 其他 API 或未验证 compat | 不注入 cache key/control，不改未知 payload，记录 `unsupported_cache_transport` | 仅 prefix candidate / diagnostic；**不得**声称 hit、miss 或节省 |

1. 以上 adapter 行为属于 `packages/ai` 对 upstream `main` 的同构补线：当前 Python port 的 `Usage` 虽有字段，stream parser 尚未填充；模型 catalog 的 cache price **不是** runtime hit 证据。
2. Reasonix package 的 A canonicalization 仅在 §2.3 已知 payload shape 生效；B compaction 仍可经 generic bridge 执行，但未知 transport 的 E 只能诊断。
3. cache namespace 至少由 `api`、provider、model、base URL、cache retention / control compatibility 标识；其中任一变化建立新 epoch，不能与旧 usage 聚合成同一 hit rate。
4. 不增加第三类自定义 adapter；新增 provider 先扩 registry、port upstream 对应 wire test、再进入 active 范围。
5. 每个 V1 adapter 的每次实际 HTTP attempt 必须在发送前恰好调用一次 `StreamOptions.onPayload`，并发送其返回的 final payload；一旦收到 HTTP response（包括非 2xx），必须恰好调用一次 `onResponse({status, headers}, model)`。网络层未收到 response 时可无该 callback；任一 adapter 不得静默绕过 A/E。

**定案一句话：** v1 是两类可证实的 transport，不是“所有模型都自动有缓存”。

### 2.14a Cache-control activation（locked grill — Q12）：**R3**

1. P3.2 的已验证 adapter 必须复刻 upstream Pi `main` 的通用 resolution：未指定 `cacheRetention` 时为 `short`；generic caller 的 `none` / `short` / `long` 必须被尊重。
2. 现有 upstream-compat `PI_CACHE_RETENTION=long` 仅作为 `packages/ai` adapter 的遗留通用兼容；它不是 Reasonix package config，不得为本包新增任何环境变量或配置 grammar。
3. `AgentOptions.cache_retention` 是 generic agent API，P3.2 将其透传到既有 `AgentLoopConfig.cacheRetention` / `SimpleStreamOptions`；直接 `Models.stream*` 调用继续使用原生 stream option。
4. Reasonix extension 不自行选择、创建或改写 provider cache controls；它只在 **P1** 为保持已选 marker 的表示语义而作的严格同值转移中移动 tool-level marker，其余情况只在 V1 adapter 给出真实 usage 后执行 E1 观测。long retention 仍受相应 model compat 约束。

**定案一句话：** cache control 的默认和 override 属于 Pi adapter / agent 通用语义；Reasonix 只消费结果，不拥有配置面。

### 2.14b Session cache identity（locked grill — Q13）：**I1**

1. 裸 `Agent` 只透传调用者给出的 `session_id`；未给出时保持 absent，adapter 按其 native 语义省略 session-scoped cache key / affinity data。
2. `AgentHarness` 必须在首个 provider request 前读取既有 `Session.getMetadata().id`，作为其 Agent 的 session identity；这是已持久 session metadata 的复用，不是新 state 或 Reasonix package storage。
3. host 和 adapter 将该值视为 opaque provider-routing data；Reasonix extension 不读取、不派生、不持久化，也不得在 diagnostic、fingerprint 或日志中暴露它。
4. 禁止为 bare Agent 或 harness 合成 UUID、prompt hash 或其他替代 identity；跨 session 的 cache share / isolation 由 caller 或现有 Session SoT 决定。

**定案一句话：** 复刻上游的 caller-owned bare Agent 与 Session-owned harness 双路径，不为 cache 自创会话身份。

### 2.14c Persistent session boundary（locked grill — Q13R）：**M3**

1. v1 复用既有 `AgentHarness` / `Session`，以支持跨进程恢复先前对话、稳定 cache affinity 与 B 的原子历史 rewrite；不新建另一套 Session、JSONL 格式、tree 或 resume 产品。
2. 这项持久化是基础 Agent 的可选宿主能力，**不是** coding TUI / CLI、workspace agent 或完整 Reasonix host；ADR 0006 / 0008 / 0009 的非目标保持不变。
3. 完整 A+B+E 的绑定路径为 Harness + Session；未绑定 transaction 的 bare `Agent` 仍可运行 A/E，但不得伪称已交付 B。
4. Session 是 host SoT；Reasonix package 只能通过既有 lifecycle / generic `CompactionPlan` transaction 消费它，不能读写 session 文件或实现 persistence。

**定案一句话：** 为恢复对话保留现有 Session host，不把持久化能力误扩成 coding-agent 产品，也不让 Reasonix 自己管理 state。

### 2.14d Harness hydration / resume（derived from Reasonix + upstream Pi）：**R4**

1. 每个高层 `AgentHarness.prompt()` 必须在 `Agent` 的 `session_start` / 首个 provider request 前，读取 `Session.build_context()` 与 `Session.get_metadata()`；将 `context.messages` 复制进 `Agent.state.messages`，并将 `metadata.id` 注入该 Agent 的 `session_id`。
2. 绑定的 `prepareNextTurn` 在每个 `turn_end` 后必须先完成 pending session writes，再按同一方式重建 Session context / metadata 并替换 loop `current_context`；不得只在发生 compaction 时重载。
3. hydration 只恢复 model-visible transcript 与 opaque session identity。model、thinking level、所有/active tools 与 system prompt 仍取当前 Harness caller configuration；不得把不完整的 `SessionContext.model` 伪装成可执行的完整 Model。
4. hydration 不得把已恢复消息再次 append 到 Session。进程重启后的 Reasonix package state（epoch / metrics / latch）是 fresh；首个 canonical outbound payload 才建立新 baseline。

**定案一句话：** Session 是每个 Harness turn 的上下文 SoT；resume 是该 SoT 的重投影，不是第二套恢复产品或模型配置恢复器。

### 2.15 System prompt 交点（locked grill — Q8）：**R2**

1. 复用现有 `build_system_prompt(base, skills, extra_sections)` 与 `Agent.state.systemPrompt`；该字符串在正常 session 路径中已被复用，作为 prefix baseline。
2. Reasonix package **不得**订 `before_agent_start`，不得注入/改写 system prompt、fewshot、日期、CWD、timestamp、session id 或 environment summary。
3. A 只在 `before_provider_request` 的 canonicalized **实际 outbound payload** 读取 system 表示并 fingerprint；其他 extension 真改 system 时按 E1 记录 break / 新 epoch，不争夺组装所有权。
4. 不新增 immutable snapshot abstraction、environment probe、跨重启 snapshot store 或平行 public hook；它们属于完整 Reasonix host，不是当前 Pi extension 接入所必需。

**定案一句话：** 现有 Pi host 已提供稳定 system prompt；本包观察并诊断，不再造一层 host。

### 2.16 指标语义（locked grill — Q9a）：**E1**

1. 唯一指标输入是 `message_end` 的最终 assistant `usage`；headers/价格 catalog 不构成 cache token 证据。
2. 逐请求记录 `cacheRead`、`cacheWrite` 和可选 `cacheWrite1h`；后者是 write 的细分，聚合时不得重复相加。
3. `prompt_total = input + cacheRead + cacheWrite`；当 `prompt_total > 0`，`cache_reuse_ratio = cacheRead / prompt_total`，否则为 `unavailable`。output 不进入分母。
4. 指标按 §2.14 cache namespace 与 epoch 分桶；不得把 model/provider/base URL/retention 已变的请求混为一个 hit rate。
5. `input` 名为 `uncached_input`，不等同 provider 的 `cache_miss`；全零 usage 也不得标为已证实 miss。`prefix_break` / `expected_cold` 仅为解释诊断。
6. 不扩 `pi_ai.Usage` 增加 Reasonix 专属 `cacheMiss`；若日后上游 Pi 引入该字段，再按同构演进。

**定案一句话：** 复用 Pi 的真实 usage 字段，报告 reusable fraction，不伪造跨 provider 的 miss 数。

### 2.17 证据门禁（locked grill — Q9b）：**T1**

1. **必过 offline adapter fixtures**：OpenAI-compatible 覆盖 cache request controls 与 DeepSeek top-level / nested usage shape；Anthropic Messages 覆盖 `cache_control` 与 read/write usage shape。两者均验证最终 `Usage` 的 upstream 语义；随机化原 tools 输入顺序后，P1 必须产出相同 tools 顺序和相同 adapter-defined tool-marker boundary；每个 adapter 还须断言 final-payload callback 与 success / non-2xx response callback 均各一次。
2. **必过 offline end-to-end**：本地 deterministic cache server 仅在连续实际 outbound payload 的可缓存 prefix 相等时回报 `cacheRead`；测试覆盖 canonical tools、append-only 请求、`message_end → E1` 指标桶，以及 prefix break 后的 `expected_cold`（不得标作实测 miss）。
3. **必过 B 逻辑链**：injected deterministic stream 验证 CompactionPlan validation、summary retry/fallback、isolated summary transport（当前 generic key/static headers/config；无 session id、tools 或 extension callback）、原子 rewrite、re-entry、新 epoch 与 L1 anti-loop；JSONL reopen 后首个 Harness request 必须使用重建 transcript 与 metadata session id，且不得重复 append 历史消息；不要求 LLM summary 字节相等。
4. **opt-in live smoke**：复用现有 `pytest.mark.live`；显式配置一个 cache-capable 的 V1 provider、凭据和足够长的稳定 prefix 后，连续第二请求**必须**观察到 `cacheRead > 0`。无明确 opt-in 配置/凭据则 skip，不作为普通 CI gate；执行时不得记录密钥。
5. headers、价格 catalog、prefix fingerprint 或 “请求成功”均不得替代第 4 项的真实 warm-cache 证据。

**定案一句话：** 离线测试决定性证明实现；一条 opt-in live warm hit 证明真实 provider 行为。

### 2.18 Package 形态（locked grill — Q17）：**N1**

```text
capability_packages/reasonix_prefix_cache/
  package.json                    # name = reasonix_prefix_cache；仅 pi.extensions
  extensions/reasonix_prefix_cache.py
```

1. 单 extension 模块订 §2.2 的既有事件；无 skills、prompts、主题、第二 extension 或 package 自定义 config grammar。
2. 本包**不注册任何 tool**。E 只复用最终 assistant `usage.cacheRead/cacheWrite` 与既有 Agent event / test path；内部 prefix / compaction diagnostics 不成为新的模型可调用 surface。
3. 不新增 status UI、host diagnostics API 或 outgoing event；这与 Reasonix 的 event/sink 展示路径不同，但符合本仓 S-engine / 无 TUI 边界。
4. 不设 JSON/YAML config、env knobs 或跨重启 package state。Reasonix policy 使用 feature 锁定的默认值及当前 model context；需要可调策略时另开 feature，而非偷加配置面。

**定案一句话：** 一个无 tool 的 extension；缓存本身不需要 status command，已有 assistant usage 就是 E 的公开证据。

### 2.19 Roadmap 位置（locked grill — Q10）：**S2**

1. 本 feature 属 **P3.2 Pi extension capability enablement**，位于完成的 P3.1 S-engine baseline 与 P4 `competitive_app` 之间（ADR 0009）。
2. `packages/ai` adapter parity 与 `packages/agent` generic CompactionPlan bridge 是 P3.2 enablement；Reasonix policy 仍是 `capability_packages/reasonix_prefix_cache` consumer。
3. search packages 与本包无业务或 lifecycle handler 冲突；P3.2 必须新增同载 tool-collision / prefix-stability gate，不能借此改变 search 行为。
4. P3.1 不回写为未完成；其 feature / plan 以版本化 P3.2 delta 演进。P4 App workflow 不承担这项 Pi 工作。

**定案一句话：** 新阶段按 Pi core ownership 划分，而不是按 capability package 目录误归 P4。

---

## 3. 规范源与角色（frozen）

| 来源 | 角色 |
|------|------|
| Reasonix **不变量**（A/B 语义） | **纪律 SoT**（概念）；不是 npm 包二进制 SoT |
| 本仓 `agent_engine_extensions_v1` + 已实现 `pi_agent.extensions` | **钩子运行时 SoT**；事件名不得另造 |
| 本仓 `packages/ai` usage / cache 字段 | **指标字节** 来源 |
| 商城 `pi-reasonix` | **有限参考**：Pi event/payload/usage adapter；非完整 Reasonix port，非 B 实现参考；其 tool-result truncation 属 D OUT |
| `@realvendex/pi-cache` | **反例**（F OUT） |
| 旧仓 competitive-agent | **无关** |

---

## 4. Open（grill 未决 — 实现前必须关掉）

| ID | 议题 | 状态 | 备注 |
|----|------|------|------|
| **Q1** | v1 柱 = A+B+E；C/D/F OUT | **closed** | §2 |
| **Q2** | 纪律落点 | **superseded** | 原 **H0** 被 B1 推翻；见 §2.1 |
| **Q2R** | 最小 host bridge 的分层 / public-surface 影响 | **closed** | **R1/P1/C1/X1** §2.9–§2.12 |
| **Q2R-a** | Plan 承载面 | **closed** | **R1** §2.9：既有 `session_before_compact` return variant |
| **Q2R-b** | Plan 身份 / 分区编码 | **closed** | **P1** §2.10：entry ID + snapshot fingerprint |
| **Q2R-c** | in-loop 时序 / re-entry | **closed** | **C1** §2.11：`prepareNextTurn` safe checkpoint |
| **Q2R-d** | 多 extension 的 compaction result / cancel collision | **closed** | **X1** §2.12：single plan；冲突 fail-closed |
| **Q3** | 事件映射表（A/B/E → 具体 `on(event)`） | **closed** | **M-core+** §2.2 |
| **Q4a** | tools schema 排序策略 | **closed** | **P1 active canonicalization** §2.3 |
| **P1-M** | adapter-selected tool cache marker 与 post-adapter canonicalization 的一致性 | **derived** | §2.3：严格同值转移到 upstream-defined canonical boundary；未知 / 多 marker fail-safe |
| **Q4b** | baseline 时机 / 动态 tool 改动的 prefix-break 语义 | **closed** | **E1 rebase** §2.4 |
| **Q5a** | B 是硬要求还是 H0 观测 | **closed** | **B1** §2.5：真实 rewrite required |
| **Q5b** | compaction bridge 分层 / 表达力 | **closed** | **G1-R / G1-P** §2.6：package plan + generic host transaction |
| **Q5c** | summary 模型、确定性、retry / fallback | **closed** | **S1** §2.8：current provider、no-tools、90s、非 deadline 一次 retry、mechanical fallback |
| **Q5d** | 完整 B 与零 host 改动的优先级 | **closed** | §2.7：完整 A+B+E；允许 generic bridge，Reasonix policy 留 package |
| **Q6** | package 名与形态（是否 status tool、配置面） | **superseded** | 原 **P1** 被 Q17/N1 替代 |
| **Q17** | 是否需要模型可调用 cache status surface | **closed** | **N1** §2.18：无 tool；复用 assistant usage / Agent event / test path |
| **Q7** | Provider 范围（DeepSeek-only vs 多 provider breakpoints / `prompt_cache_key`） | **closed** | **V1** §2.14：verified OpenAI-compatible + Anthropic Messages registry |
| **Q8** | system 组装交点（host base vs extension 改写；date/CWD 政策） | **closed** | **R2** §2.15：复用现有 host prompt；outbound-observed；无 package 注入 |
| **Q9** | 指标定义与验收（Offline faux vs Live 真 cache） | **closed** | **E1 + T1** §2.16–§2.17 |
| **Q9a** | 指标字段 / 分母 / miss 语义 | **closed** | **E1** §2.16：upstream-aligned reuse ratio |
| **Q9b** | offline / live 的验收证据 | **closed** | **T1** §2.17：deterministic fixtures + one opt-in live |
| **Q10** | Roadmap 阶段名 / 与 search 包关系 | **closed** | **S2** §2.19：P3.2 Pi extension stage；search 同载 gate |
| **Q11** | H0 下是否需要 ADR | **superseded** | 原「无需 ADR」结论仅适用 H0 |
| **Q11R** | B1 host bridge 是否触及架构/ADR | **closed** | §2.13：bridge 分层不新造 hook；**Q10/S2 以 ADR 0009 / v0.3.5 治理阶段顺序** |
| **Q12** | provider cache control 默认 / override 所有权 | **closed** | **R3** §2.14a：upstream default short；generic control；package 无 config/env |
| **Q13** | cache namespace 的 session identity 来源 | **closed** | **I1** §2.14b：bare caller-owned；harness 复用 `Session.getMetadata().id`；无合成 ID |
| **Q14** | 自动 compaction 的 usage 来源 / 阈值 | **closed** | **T2** §2.8a：turn_end；`tokens > contextWindow - 16_384`；保留约 20k tail |
| **Q13R** | 基础 Agent 的持久状态模型 | **closed** | **M3** §2.14c：复用既有 Harness / Session 以支持 resume；不是 coding-agent 产品 |
| **R4** | Harness 的 session hydration / resume 时序 | **derived** | §2.14d：每 turn 从 Session 投影 messages + metadata id；配置仍由当前 Harness 持有 |
| **Q15** | 小 context window 下固定阈值的安全降级 | **closed** | **W2 / W2a** §2.8b：adaptive，不禁用 B |
| **Q15a** | adaptive reserve / tail / summary 的精确公式 | **closed** | **W2a** §2.8b：20% / 50% capped，summary ≤ 80% reserve |
| **L1** | auto-compaction stuck guard | **derived** | §2.8e：两次连续 committed auto rewrite 后 pause，usage 回落才解除 |
| **Q16** | compaction summary 的确定性边界 | **closed** | **D1** §2.8c：transaction / fallback deterministic；LLM summary 可变、新 epoch |
| **Q18** | compaction 中的 verbatim retain 集与通用 summary 内容 | **closed** | **K1 + K2-R** §2.8d：所有 small user entries + prior summaries + tail；generic continuation headings |
| **Q20** | Reasonix 的 all-small-user retain floor 与 K1 first-only 冲突 | **closed** | **K2-R** §2.8d：与 Reasonix 一致，保留所有足够小的 user entries |
| **Q21** | payload transform 冲突 / extension load 顺序 / terminal 最终性 | **closed** | **§2.2**：ADR 0006 下 v1 为闭合一方能力集，Reasonix 是唯一 payload mutator ⇒ **构造性 terminal**；无有序 load plan、无 runner phase、无公开 order hook；`enabled` 保持无序 whitelist；重挂载=新 epoch；未来多 mutator 由 Reasonix+search 组合门禁约束（Q21c–f superseded；Q21g/h 保留） |
| **F1** | freeze | **closed** | **v0.1.0 frozen**；全部 Q closed/superseded/derived；实现以 [`P3_2_pi_extension_capability_enablement.md`](../plans/P3_2_pi_extension_capability_enablement.md) 为准 |

---

## 5. 与相关文档的关系

| 文档 | 关系 |
|------|------|
| `agent_engine_extensions_v1` | **硬依赖**；P3.1 baseline 的 P3.2 versioned delta 必须先完成 |
| `search_capability_packages_v1` | 并列 consumer；无业务依赖；P3.2 必有同 session load / prefix compatibility gate |
| ADR 0006 / 0008 / **0009** | 本地 only；S-engine baseline；P3.2 enablement 边界 |
| 商城包 README | 参考，非契约 |

---

## 6. 验收（locked — Q9）

| 层 | 必过断言 |
|----|----------|
| Offline adapter | §2.17(1) 的 OpenAI-compatible / Anthropic request + usage fixtures |
| Offline extension E2E | §2.17(2) 的实际 payload prefix、E1 propagation、break/epoch 语义 |
| Offline compaction | §2.17(3) 的 plan、rewrite、retry/fallback、re-entry |
| Offline resume | §2.14d 的 JSONL reopen、first outbound context / metadata id、无历史重复 append |
| Live opt-in | §2.17(4) 的同一已配置 cache-capable provider 第二请求 `cacheRead > 0` |

普通 CI 只运行 deterministic offline 门禁；live test 缺少明确 opt-in 配置或凭据时 skip，配置后失败即表示该环境未证明 warm-cache 行为。

---

## 7. 变更记录

| 版本 | 日期 | 说明 |
|------|------|------|
| 0.0.1 | 2026-07-26 | draft 创建；**Q1 locked**：v1 = A+B+E，C/D/F OUT |
| 0.0.2 | 2026-07-26 | **Q2 locked = H0**；Q11 closed（无 ADR）；交付 = 纯 extension 包 |
| 0.0.3 | 2026-07-26 | **Q3 locked = M-core+**；E 加只读 `message_end`，记录 callback / fewshot 运行时限制 |
| 0.0.4 | 2026-07-26 | **Q4a locked = P1**；已知 OpenAI/Anthropic tools payload 主动 canonicalize；schema array 不重排 |
| 0.0.5 | 2026-07-26 | **Q4b locked = E1**；首个 canonical payload 建基线；break 后新 epoch，不伪称实测 miss |
| 0.0.6 | 2026-07-26 | **Q5a locked = B1**；H0 / 原 Q11 结论 superseded；B 需要真实通用 host compaction bridge，未锁具体实现 |
| 0.0.7 | 2026-07-26 | **Q5b locked = G1-R/G1-P**；完整 plan 在 package，generic transaction 在 host；`pi-reasonix` 限为 adapter 参考 |
| 0.0.8 | 2026-07-26 | **Q5d locked**：完整 A+B+E 优先于 Pi 零实现改动；允许 generic host bridge，不改变 Reasonix package 边界 |
| 0.0.9 | 2026-07-26 | **Q5c locked = S1**：current provider 无-tools summary、90s、非 deadline 一次 retry、deterministic mechanical fallback；LLM 摘要不要求字节稳定 |
| 0.0.10 | 2026-07-26 | **Q2R-a locked = R1**：`session_before_compact` 返回 typed `compactionPlan`；`ctx.compact()` 仅触发，host 负责验证 / summary / rewrite |
| 0.0.11 | 2026-07-26 | **Q2R-b locked = P1**（entry IDs + snapshot fingerprint）；**Q2R-c derived = C1**（同 loop `prepareNextTurn` checkpoint，非 agent 结束后延后） |
| 0.0.12 | 2026-07-26 | **Q2R-d derived = X1**：Reasonix single-writer 不变量；plan 唯一，mixed / multiple plan fail-closed，legacy result 仍 upstream last-result |
| 0.0.13 | 2026-07-26 | **Q11R closed**：R1/P1/C1/X1 留在 ADR 0008 / v0.3.4 边界内；实现前必须升 extension feature contract 并加 P3.1 plan delta |
| 0.0.14 | 2026-07-26 | **Q7 locked = V1**：已验证 OpenAI-compatible 与 Anthropic Messages active transport；Python `packages/ai` 需按 upstream 补 usage/cache controls；未知 provider diagnostics only |
| 0.0.15 | 2026-07-26 | **Q8 locked = R2**：最小 extension 接入；复用现有 system prompt，仅观测 outbound payload；后续选择遵循 §2.0 最小桥接纪律 |
| 0.0.16 | 2026-07-26 | **Q9a locked = E1**：保持 Pi `Usage`；per-namespace/epoch `cache_reuse_ratio`；不新增伪通用 `cacheMiss` |
| 0.0.17 | 2026-07-26 | **Q9b locked = T1**：两 adapter deterministic fixtures + local prefix-cache E2E；一个 opt-in live warm-hit smoke；**Q9 closed** |
| 0.0.18 | 2026-07-26 | **Q6 locked = P1**：单 extension + 只读 status tool；无 package config / skills / prompts / host diagnostics API |
| 0.0.19 | 2026-07-26 | **Q10 locked = S2**：ADR 0009 / contract 0.3.5 / roadmap P3.2；Reasonix 按 Pi extension ownership，不归 P4 App |
| 0.0.20 | 2026-07-26 | 对齐 **Q11R** 与 Q10/S2：bridge 分层不新造 hook；P3.2 阶段顺序已由 ADR 0009 / v0.3.5 正式治理 |
| 0.0.21 | 2026-07-26 | **Q12 locked = R3**：复刻 upstream default short；generic `cache_retention` / adapter compat，不给 Reasonix package 增加配置面 |
| 0.0.22 | 2026-07-26 | **Q13 locked = I1**：裸 Agent 透传 caller ID；harness 复用 Session metadata ID；Reasonix 不读取、持久化或暴露该值 |
| 0.0.23 | 2026-07-26 | **Q14 locked = T2**：复用 Pi `16_384` reserve / `20_000` tail；turn_end usage 驱动 C1 请求；无 package tuning config |
| 0.0.24 | 2026-07-26 | **Q13R locked = M3**：为跨进程恢复复用既有 Harness / Session；保持基础 Agent 边界，Reasonix 不管理 persistence |
| 0.0.25 | 2026-07-26 | **Q15/Q15a locked = W2/W2a**：小窗口用 20% reserve / 50% tail capped policy；summary ≤ 80% reserve；无有效 fold fail-safe |
| 0.0.26 | 2026-07-26 | **Q16 locked = D1**：对齐 Reasonix 的 transaction / fallback deterministic 边界；正常 LLM summary 可变并重建 epoch |
| 0.0.27 | 2026-07-26 | **Q17 locked = N1**：删除非必要 `reasonix_cache_status`；E 复用既有 assistant usage / event，不加 UI / host diagnostics API |
| 0.0.28 | 2026-07-26 | **Q18 locked = K1**：移植 Reasonix 的 anti-drift retain floor；固定基础 Agent continuation summary，无 coding 专用栏目 |
| 0.0.29 | 2026-07-26 | **Q20 locked = K2-R**：与 Reasonix `partitionFold` 对齐；所有足够小的 user entries、旧摘要与 tail 保留，避免中途用户约束只依赖 LLM summary |
| 0.0.30 | 2026-07-26 | **R4/L1 derived**：按 Reasonix `SetSession`、upstream Pi per-turn Session projection 与 Reasonix two-rewrite stuck guard 固化 Harness hydration / anti-loop 行为 |
| 0.0.31 | 2026-07-26 | **S1 source-derived supplement**：summary 是不带 Agent session identity / extension lifecycle 的 isolated simple completion；其 usage 不得污染 E1 baseline 或会话指标 |
| 0.0.32 | 2026-07-26 | **P1-M derived**：对齐 upstream adapter 在最后 tool 的 `cache_control` placement；P1 排序后只同值转移该 marker，不取得 cache-control policy 所有权 |
| 0.0.33 | 2026-07-26 | **V1 callback-parity derived**：每个 active adapter 对每次 HTTP attempt 都透传 final `onPayload`，并在收到任意 HTTP response 时透传一次 `onResponse`；A/E 不允许 adapter-specific 静默缺口 |
| 0.0.34 | 2026-07-26 | **T2 event-map reconciliation derived**：`turn_end` 是唯一为 threshold request 订阅的 turn event；只读 usage 并登记 `ctx.compact()`，实际 rewrite 仍只在 C1 |
| 0.0.35 | 2026-07-26 | **Terminology reconciliation derived**：Q3 返回为 `compactionPlan`（非 legacy result）；E 只报告真实 read/write 与 `expected_cold`，不承诺 provider `cacheMiss` |
| 0.0.36 | 2026-07-26 | **S1 transport-resolution supplement**：summary 复用 generic key / static-header / retention resolution，却剥离 session identity 并绕过全部 extension callbacks，避免既失配 provider 又污染 A/E |
| 0.0.37 | 2026-07-26 | **Q21c locked**：payload transform 冲突采用 Pi 式显式、host-owned extension load plan；不新增 runner priority/final phase。 |
| 0.0.38 | 2026-07-26 | **Q21d/Q21e locked**：terminal 语义要求封闭的完整启用集合；复用有序 `enabled` list 表达该 plan，`None` 自动发现不提供最终性。 |
| 0.0.39 | 2026-07-26 | **Q21f locked**：有序 plan 的重复/未知/disabled 项报告 diagnostic 并跳过；有效项尽力按原相对顺序加载，最终性以实际 attached 集合判断。 |
| 0.0.40 | 2026-07-26 | **Q21g locked**：保留 Pi 式 extension reload；Reasonix runtime 重挂载后从首个 canonical outbound payload 新建 epoch，禁止跨 runner 聚合指标。 |
| 0.0.41 | 2026-07-26 | **Q21h locked**：terminal 是配置不变量而非运行时门禁；不加 loader admission gate/公开 order hook；fingerprint 为观测诊断，metrics 恒诚实，terminal 位置由有序 `enabled` + 组合门禁验证。 |
| 0.0.42 | 2026-07-26 | **Q21 简化（Q21c–f superseded）**：采纳闭合一方能力集模型 —— search/echo 仅 registerTool、Reasonix 为唯一 payload mutator，terminality 按构造成立；收回有序 `enabled` load plan，`enabled` 回归无序 whitelist；未来改 payload 的一方包由组合门禁约束在 Reasonix 之前；Q21g（重挂载=新 epoch）、Q21h（无运行时门禁 / 指标恒诚实）保留。 |
| 0.1.0 | 2026-07-26 | **F1 freeze**：全部 Q closed/superseded/derived；status → **frozen**；plan 指向 `P3_2_pi_extension_capability_enablement.md`。 |
