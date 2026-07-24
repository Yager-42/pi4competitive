# Feature 边界契约：agent-engine-extensions-v1

| 字段 | 值 |
|------|-----|
| **feature_contract_version** | `0.2.2` |
| **status** | **frozen** |
| **updated** | 2026-07-24 |
| **feature_id** | `agent-engine-extensions-v1` |
| **roadmap_stage** | **P3.1**（`P3-extensions`：本地 package 子集加厚 extension 运行时；非 P4 业务） |
| **architecture_contract** | [`ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.4**（ADR **0008** accepted） |
| **roadmap** | [`ROADMAP.md`](../ROADMAP.md) |
| **plan** | [`docs/plans/P3_1_agent_engine_extensions.md`](../plans/P3_1_agent_engine_extensions.md) **v0.2.3 completed** |
| **path** | `docs/features/agent_engine_extensions_v1.md` |
| **upstream SoT** | `earendil-works/pi` **`main`**：`packages/coding-agent/src/core/extensions/**`（及与之同构的 package 资源加载语义） |
| **local vendor mirror** | `vendor/earendil-works-pi/packages/coding-agent/src/core/extensions/` |

---

## 0. 效力与状态

1. 本文是 **agent 引擎 extension 钩子面** 的 **frozen** 功能边界；架构契约 **v0.3.4** + **ADR 0008** 已落地（A1）；实现按 plan **P3.1**。
2. 标为 **locked** 的决定不得由实现者自行改写；变更须重新 grill 并升 `feature_contract_version`，并同步 Roadmap。
3. §8 Open 在 freeze 时仅保留已 closed 记录；无未决实现拍板项。实现细节见后续 `docs/plans/`。
4. 架构、import 方向、本地 package 子集仍以架构契约 + ADR 0006 为最高约束；本文若与之冲突 → **先 ADR**。
5. **不做** 完整 pi coding-agent TUI / CLI 产品；Pi 在本仓定位为 **项目内 agent 核心引擎**。

---

## 1. 动机与目标（locked grill）

### 1.1 问题

本仓 P3 已实现 coding-agent package-manager **本地子集**，但 extension 面极薄：

```text
capability package → register(api) → 仅 add_tool / add_skill / add_prompt_template
                 → apply_capability_report → 只 merge tools 进 Agent
```

**缺失：** 上游 extension **事件钩子 + runner + 接到 agent 生命周期**。  
因此无法用 package/extension 方式接入 **Reasonix 类前缀缓存**（改 system / payload / compact），只能 host 手写 `on_payload` 等。

### 1.2 目标

1. 按上游 **同构翻译**（代码翻译，不重设计架构与事件名）补齐 **agent 引擎可用的 extension 子系统**。
2. 使本地 `capability_packages/*` 内的 extension 能：
   - `registerTool`（对齐上游，取代本仓临时 `add_tool`）；
   - `on(<engine lifecycle event>)` 并由 **runner** 在 loop 对应点 **dispatch**。
3. 保持本仓产品定位：**引擎，非 TUI**。

### 1.3 非目标（locked grill）

| 不做 | 说明 |
|------|------|
| 完整 pi CLI / coding-agent TUI | 无交互终端产品目标 |
| `ui.*` / theme / TUI command UX | 见 §4 out |
| npm / git / `pi install` / `~/.pi` 发现 | 维持 ADR 0006 omit |
| 第二 agent 内核 / 整仓 Reasonix 替换 | D12/G3；Reasonix 仅作后续 **可选 extension** 参考 |
| 本 feature 内实现 Reasonix 缓存业务包 | 本 feature 只交付 **钩子运行时**；缓存包另开 feature |
| 重设计事件名或自创半套 Hook API | 禁止 |

---

## 2. 规范源与角色（locked grill）

| 来源 | 角色 |
|------|------|
| `packages/coding-agent/src/core/extensions/{types,loader,runner,wrapper}.ts`（main） | **Extension 子系统 SoT** — 类型、注册、dispatch、加载语义 |
| 上游 package 资源解析中与 **extension 加载** 相关的部分 | E2 范围内同构；install 通道除外 |
| 本仓 `packages/agent` Agent / agent_loop | **emit 接线宿主** — 在同构生命周期点调用 runner |
| 本仓现有 `package_manager`（ADR 0006） | E2 下 **演进为** 与上游同构的本地发现+加载；不是永久并行第二套 |
| 商城 `pi-reasonix` 等 | **后续消费者参考**；非本 feature 交付物 |
| 旧仓 competitive-agent | **与本 feature 无关** |

---

## 3. 产品裁切：S-engine（locked grill）

**定案名：S-engine**

```text
IN  — 与 agent 引擎生命周期相关的 extension 面
      （事件名 / handler 签名 / runner / registerTool / 本地 load）
OUT — TUI / UI / theme / 依赖 hasUI 的交互 API / 完整 coding-agent 产品壳
```

| 类别 | 状态 |
|------|------|
| `on(event)` — engine 生命周期事件 | **IN** — 完整表见 §3.1 |
| `registerTool` / 工具注册进入 Agent | **IN** |
| runner 注册表 + 按事件 dispatch + 返回值语义（与上游一致） | **IN** |
| 本地 package 发现 + extension 模块 `register(api)` | **IN**（E2） |
| `ExtensionContext` 引擎字段 | **IN** — **C1 / §3.2** |
| `ExtensionContext.ui` / notify / select / custom / theme | **OUT** |
| settings trust UI、`-e` CLI 临时包产品行为 | **OUT** |
| npm/git install | **OUT**（ADR 0006） |
| session 树 / fork / switch / `resources_discover` 等事件 | **OUT**（§3.1） |

**原则：** OUT 项 **不出现在本仓公开 API**。IN 项 **按上游翻译**，不另起事件命名。

### 3.1 事件表（locked grill：**O2**）

上游 `ExtensionAPI.on` 事件按 **S-engine** 裁切如下。  
**IN** = 本 feature 必须支持 `on` 注册，并在 agent/harness 对应点 **emit**。  
**OUT** = 不进入本仓公开 API（无 `on` 重载、无 emit 义务）。

#### IN（引擎）

| 事件 | 备注 |
|------|------|
| `session_start` / `session_shutdown` / `session_info_changed` | 会话生命周期 |
| `session_before_compact` / `session_compact` | 压缩 |
| `context` | 可改 messages |
| `before_provider_request` / `before_provider_headers` / `after_provider_response` | provider 请求路径 |
| `before_agent_start` / `agent_start` / `agent_end` / `agent_settled` | 跑次；可改 systemPrompt |
| `turn_start` / `turn_end` | 回合 |
| `message_start` / `message_update` / `message_end` | 消息；可改 finalized message |
| `tool_execution_start` / `tool_execution_update` / `tool_execution_end` | 工具执行观测 |
| `tool_call` / `tool_result` | 可 block / 改 result |
| `model_select` / `thinking_level_select` | 本仓 Agent/session 已有对应概念 |

#### OUT（本 feature 明确不做）

| 事件 | 原因 |
|------|------|
| `project_trust` | 信任/TUI 产品 |
| `input` | TUI 输入变换 |
| `user_bash` | 交互 bash |
| `session_before_switch` / `session_before_fork` / `session_before_tree` / `session_tree` | session 树 UX；**OUT**（非 defer） |
| `resources_discover` | 资源发现扩展钩；**OUT** |

**禁止** 为 OUT 事件保留永久 no-op `on` 重载假装完整 coding-agent。

### 3.2 ExtensionContext：C-engine / C1（locked grill）

| 状态 | 字段 / 方法 |
|------|-------------|
| **IN** | `cwd`；只读 `sessionManager`（本仓 session 只读视图）；`model` / `modelRegistry`（或本仓等价）；`signal` / `abort()` / `isIdle()`；`getContextUsage()`；`compact()`；`getSystemPrompt()`；`hasPendingMessages()`；`shutdown()`（映射为结束 agent 运行，非退出进程 CLI） |
| **OUT** | 整个 `ui: ExtensionUIContext`；`hasUI`；TUI/RPC 产品向 `mode`（若保留 `mode` 仅允许引擎占位值，plan 钉死）；`ExtensionCommandContext` 的 fork/switch/navigateTree/newSession 等；`isProjectTrusted()` |

**错误语义：** OUT 字段 **不出现在公开类型**。IN 方法在某次运行未接线时 **显式抛错**，禁止静默 no-op 伪装成功。


---

## 4. 范围：E2（locked grill）

| 代号 | 含义 | 本 feature |
|------|------|------------|
| E1 | 仅 extensions runner + 手写接到 Agent；发现仍完全旧 loader | 否 |
| **E2** | **extensions 子系统同构 + package 资源解析/extension 加载同构；仍 omit npm/git/home** | **是** |
| E3 | 对齐整段 coding-agent 启动链（settings/trust/CLI…） | 否 |

E2 含义：

- **所有** `capability_packages/*`（含现有 search 三包）走 **同一条** extension 加载链；
- **不是**「老包旧 runtime、新包新 runtime」双轨。

- **SK2（locked grill）：** package 内 **skills / prompts 资源** 与 tools 同级：E2 load 进 report，且 **apply 接到现有 harness** 技能/提示面，使 Agent 运行时可用；不在 ExtensionAPI 上自创 `add_skill` 平行品牌（资源发现走上游 package 形状；工具仍 `registerTool`）。

---

## 5. 与现有 package 的关系：M2（locked grill）

| 代号 | 含义 | 本 feature |
|------|------|------------|
| M1 | 保留 `add_tool` 兼容层 | **否** |
| **M2** | **一次对齐上游 `registerTool` 等形状；无兼容层、少胶水** | **是** |
| M1→M2 两阶段 | 先兼容后删 | **否** |

### 5.1 对现有 search 三包的影响（locked grill）

| 项 | 要求 |
|----|------|
| 业务逻辑（HTTP、normalize、env fail-closed、envelope） | **不改** |
| `register` 胶水 | **改** 为上游对齐的 `registerTool`（及 API 对象形状） |
| 加载路径 | 统一 E2；**无**永久双栈 |
| search feature 契约 | 已升至 v0.1.12 并对齐 `api.registerTool`；业务 HTTP/normalize 不变 |

### 5.2 对 `CapabilityRegisterApi` 的影响（locked grill）

- 现有 `CapabilityRegisterApi`（仅 add_tool/skill/prompt）视为 **P3 临时子集**，本 feature 以 **上游 ExtensionAPI 的引擎子集** 替换；
- **不**长期保留双 API 或别名兼容层（M2）。

### 5.3 与现有 Agent host 回调：H1（locked grill）

| 代号 | **H1** |
|------|--------|
| **定案** | **Runner 统一**：agent loop 只通过 extension 事件 emit；平行 host 回调不作为长期公共 API |
| **范围** | 至少包括现有/计划中的 `on_payload`、`transform_context` 等与「改 context/payload」同职责的入口 |
| **迁移** | App/wiring 若需定制：注册 extension（`api.on(...)`）或由宿主组装等价 extension；**禁止**长期双路径 |
| **实现** | 干净删除公开 host 钩子，或实现期短暂 private 后删；**不**保留 H2 顺序并存、**不**用 H3 别名层 |

### 5.4 挂载形状：AP3（locked grill）

| 代号 | **AP3** |
|------|--------|
| **定案** | **公开 API 与上游 host 组装符号同构**（Python 名可 snake_case，语义一一对应），**不**自创第三套 apply 品牌作为长期 SoT |
| **上游对照（至少）** | `createExtensionRuntime` / `loadExtensions`（及 cached 变体）/ `ExtensionRunner` / `wrapRegisteredTools`；session/agent 侧 runner 绑定与 emit 对照 `agent-session` 中 runner 用法 |
| **本仓现状** | `load_capability_packages` + `apply_capability_report` 为 P3 临时面；本 feature **收敛** 到上游形状。允许短暂薄包装，**禁止**长期双 SoT |
| **职责** | load → runtime + 注册 tools/skills/prompts/handlers；`ExtensionRunner` 持有并 dispatch §3.1 IN 事件；Agent/loop 持 runner 引用；**SK2** 接线 skills/prompts |


---

## 6. 落点与分层（locked grill）

### 6.1 逻辑分层（locked grill）

```text
┌──────────────────────────────────────────────┐
│  Extension 子系统（types / loader / runner）   │  ← 上游 coding-agent/core/extensions 翻译
│  提供：ExtensionAPI、事件 dispatch              │
└──────────────────┬───────────────────────────┘
                   │ register(api) / emit
                   ▼
┌──────────────────────────────────────────────┐
│  packages/agent  Agent loop（emit 点）         │  ← 引擎宿主接线
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  capability_packages/*  extensions            │  ← 消费者（tool 包、未来缓存包）
└──────────────────────────────────────────────┘
```

- 钩子运行时 = **宿主能力**，不是某个业务 package「反向注入」。
- 业务 extension（含未来 Reasonix 类）= **消费者**。

### 6.2 代码落盘路径（locked grill：**P-b**）

| 项 | 值 |
|----|-----|
| **代号** | **P-b** |
| **树** | `packages/agent/src/earendil_works/pi_agent/extensions/`（名称可微调，须在 plan 钉死） |
| **import** | `earendil_works.pi_agent.extensions`（及子模块 types/loader/runner/…） |
| **模块切分** | 对齐上游 `core/extensions/*`；文件头标注 `upstream: packages/coding-agent/src/core/extensions/...` |
| **不做** | 新建独立 `packages/coding_agent` 空壳产品包（无 TUI 目标） |

**约束：** 不得把竞品 domain 放进 extensions；不得引入第二 LLM 框架。

---

## 7. 实现原则（locked grill）

1. **同构翻译**：事件名、handler 方向、dispatch 顺序、registerTool 语义对照 upstream main；Python 惯用 asyncio / 类型注解。
2. **Host delta 仅限必要**：`.ts`+jiti → `.py`+importlib（已有）；无 TUI 导致的 Context 裁剪须在本文 §3/§8 列表化。
3. **禁止** 为省事发明平行 Hook 名称或「本仓专用」半套 API。
4. **ADR 0006**：本地 only；install omit 不变，除非另开 ADR。
5. **本 feature 验收** 以「引擎事件可被 extension 订阅并影响 payload/tools」为准，不以「跑通 pi TUI」为准。

---

## 8. Open（grill 未决 — 实现前必须关掉）

| ID | 议题 | 备注 |
|----|------|------|
| O1 | ~~物理模块路径~~ → **P-b**（§6.2） | **closed** |
| O2 | ~~事件表~~ → **§3.1** | **closed** |
| O3 | ~~ExtensionContext~~ → **C1 / §3.2** | **closed** |
| O4 | ~~skills/prompts~~ → **SK2** | **closed** |
| O5 | ~~host 回调~~ → **H1** | **closed** |
| O6 | ~~Roadmap~~ → **R1 = P3.1** | **closed** |
| O7 | ~~apply 形状~~ → **AP3**（§5.4） | **closed** |
| O8 | ~~验收~~ → **AC1** §10 整表 locked | **closed** |
| O9 | ~~ADR~~ → **A1**（0008 + 契约升版） | **closed** |
| O10 | ~~freeze~~ → **F1** status **frozen** v0.2.0 | **closed** |

---

## 9. 与相关文档的关系

| 文档 | 关系 |
|------|------|
| `docs/features/search_capability_packages_v1.md` | 消费者；本 feature 落地后须更新其 §3.2 `add_tool` 描述 |
| ADR 0006 | 本地子集 + omit install；E2 是子集 **加厚** 非恢复远程 install |
| `docs/plans/P3_capability_loader.md` | 历史 P3；本 feature 是其后的引擎补全 |
| Reasonix / `pi-reasonix` | 后续可选 extension；**不在**本 feature 交付 |

---

## 10. 验收标准（locked grill：**AC1** / O8）

**退出门 = Offline 全绿 + Live 全绿（有密钥时）。**  
无密钥时 Live **skip 不算 fail**，但 **宣称 P3.1 done 前** 本地/CI 须至少跑通一次完整 Live（与 search 包 L 门同纪律：密钥齐全才算 L 通过）。

### 10.1 同构与裁切（Offline contract）

1. `earendil_works.pi_agent.extensions` 模块边界可映射 upstream `core/extensions/{types,loader,runner,wrapper}`；文件头含 `upstream:` 路径。
2. §3.1 **IN** 事件均可 `on` 注册；对应 agent/harness 点有 emit（plan §2.4 全表必须）。
3. §3.1 / §3.2 **OUT** 不出现在公开 API（无 ui、无 session 树事件、无 resources_discover 等）；`on(OUT)` **拒绝**（raise 或 load diagnostic）。
4. 公开挂载符号遵循 **AP3**（`create_extension_runtime` / `load_extensions` / `ExtensionRunner` / `wrap_registered_tools` 等与上游语义对应）；P3 `apply_capability_report` 不得与 runner **双 SoT** 并存于最终态。

### 10.2 Offline 功能与边界（高覆盖，逻辑链路）

目标：链路逻辑正确 + **边界/失败路径** 有测试，不单测 happy path。

| ID | 断言 |
|----|------|
| **O1** | 测试 extension：`registerTool` / `register_tool` 注册的 tool 经 wrap 后可被 Agent（**faux**）调用；M2 后 search 三包 + echo offline 仍绿 |
| **O2** | 订阅 `before_provider_request` **或** `before_agent_start` 可 **可观测** 修改/替换 payload 或 systemPrompt（runner merge 语义） |
| **O3** | 订阅 `session_before_compact` **或** `message_end` 至少一类 handler 返回值生效（cancel / 同 role 替换 message 等） |
| **O4** | **SK2**：带 skills/prompts 的 fixture package load 后 harness 可读到资源 |
| **O5** | **H1**：无公开 `on_payload` / `transform_context` 作为改 payload/context 的正式入口 |
| **O6** | OUT 事件 `on` 被拒绝；公开 Context **无** `ui` / `hasUI` |
| **O7** | 多 handler **顺序**与 merge（如 systemPrompt 链式覆盖；`tool_call` 遇 `block` 短路） |
| **O8** | 边界：坏路径 / 非 `.py` / register 抛错 → load errors/diagnostics，不 silent success；空 extension 允许 |
| **O9** | 边界：`tool_call` block；`message_end` 改 role 被拒绝并记 error；handler 抛错 → `emit_error` 且不拖垮 runner |
| **O10** | 边界：runtime 未 `bind_core` 时 action 桩 **抛错**；stale/invalidate 后 ctx 使用抛错 |
| **O11** | 无 TUI、无 install/npm/git/`~/.pi` 路径（ADR 0006）；无第二内核；不交付 Reasonix 业务包 |

### 10.3 Live 功能（真实跑通 — 主路径必过，非全事件表）

使用仓库既有 live 纪律：`OPENAI_API_KEY` / `MODEL_API_KEY` 等（`tests/live_env`）；**禁止**在日志/断言中打印密钥。

**Live 只证明 mock 替不掉的真实路径**；§3.1 全表 emit、block/merge 边界、H1/OUT/stale、SK2、search 三包 live、compact 产品环 **不** 要求 P3.1 Live（Offline / 既有 live_compaction / search live 负责）。

| ID | 断言 |
|----|------|
| **L1** | **假 extension 包**（tmp 或 `tests/.../fixtures/live_ext_pkg`）：`register(api)` + `registerTool` 真实 load → report/runner 中可见 tool 名 |
| **L2** | 将该 extension attach 到 **真实模型** Agent；模型 **实际发起 toolCall** 并得到 **toolResult**（内容可观测，非空） |
| **L3a** | **必过**：`before_agent_start` 改 **systemPrompt** 后真跑一轮；可观测生效（如 system 内容进入请求路径 / 响应或探针可证明） |
| **L3b** | **必过**：`before_provider_request` 改或标记 **payload** 后真跑一轮；可观测生效（与 L3a **两条都要**，非三选一） |
| **L4** | M2 后 `echo_example`（或等价 capability 包形状）live：load → apply/attach → 真模型调用 echo 类 tool 成功（可与 L2 共用模型，但须覆盖 package 发现路径） |
| **L5** | 无密钥：live 用例 **skip**；有密钥：**L1 + L2 + L3a + L3b + L4 全部 pass** 方可宣称 P3.1 done |

### 10.4 文档联动

14. 实现完成后：升版 `search_capability_packages_v1` 中过时 `add_tool` 描述；Roadmap **P3.1=done**；ADR 0008 + 契约 0.3.4 已存在（A1 docs）。

---

## 11. Grill 决策日志

| 日期 | 决策 | 代号 |
|------|------|------|
| 2026-07-24 | 新 feature 文档；同构 extension 钩子面 | — |
| 2026-07-24 | 缺 types+loader+runner+loop 接线 | — |
| 2026-07-24 | coding-agent extensions 子系统语义 | **B** |
| 2026-07-24 | extensions + 本地 package 加载同构；omit install | **E2** |
| 2026-07-24 | 一次对齐 `registerTool`；无兼容层 | **M2** |
| 2026-07-24 | 只要 agent 引擎，不要 coding TUI | **S-engine** |
| 2026-07-24 | 本 feature 只交付钩子运行时；Reasonix 另开 | — |
| 2026-07-24 | 代码落 `pi_agent/extensions/` | **P-b** |
| 2026-07-24 | Runner 统一；删平行 host 回调 | **H1** |
| 2026-07-24 | 事件 IN/OUT；session 树与 resources_discover OUT | **O2** |
| 2026-07-24 | 先 ADR 0008 + 架构契约升版 | **A1** |
| 2026-07-24 | Roadmap **P3.1** | **R1** |
| 2026-07-24 | skills/prompts load+apply | **SK2** |
| 2026-07-24 | ExtensionContext C-engine | **C1** |
| 2026-07-24 | 挂载 API 上游同构；收敛 P3 apply | **AP3** |
| 2026-07-24 | 验收 §10 整表 locked | **AC1** |
| 2026-07-24 | feature 契约 freeze | **F1** |
| 2026-07-24 | ADR 0008 + 契约 0.3.4 + roadmap P3.1 + plan | **A1 docs** |
| 2026-07-24 | 验收加 **完整 Live**（假 extension + 真模型 toolCall）+ Offline 高覆盖边界 | **AC1+** |
| 2026-07-24 | Live 收紧：L3a systemPrompt + L3b payload **均必过**；非全链路 live | **AC1++** |

---

## 12. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| 0.1.0 | 2026-07-24 | 草案：E2/M2/S-engine/B |
| 0.1.1 | 2026-07-24 | **P-b**；O1 |
| 0.1.2 | 2026-07-24 | **H1**；O5 |
| 0.1.3 | 2026-07-24 | **O2** 事件表 |
| 0.1.4 | 2026-07-24 | **A1** ADR-first；O9 |
| 0.1.5 | 2026-07-24 | **R1** P3.1；O6 |
| 0.1.6 | 2026-07-24 | **SK2**；O4 |
| 0.1.7 | 2026-07-24 | **C1** Context；O3 |
| 0.1.8 | 2026-07-24 | **AP3** 挂载形状；O7 |
| 0.1.9 | 2026-07-24 | **AC1** §10 验收；O8 |
| 0.2.0 | 2026-07-24 | **frozen**（F1）；grill 收口 |
| 0.2.1 | 2026-07-24 | **AC1+**：Offline O1–O11 高覆盖；Live L1–L5 真模型/假 extension 必过（有密钥）；仍 frozen |
| 0.2.2 | 2026-07-24 | Live：**L3a/L3b 双钩子必过**（systemPrompt + payload）；明确非 live 范围；仍 frozen |
