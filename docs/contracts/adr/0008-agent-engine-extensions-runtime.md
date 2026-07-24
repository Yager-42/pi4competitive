# ADR 0008: P3.1 加厚 coding-agent **extension 运行时**（引擎子集同构）

- **status:** accepted
- **date:** 2026-07-24
- **contract_version_before:** 0.3.3
- **contract_version_after:** 0.3.4
- **extends:** ADR 0006（本地 package 子集；install omit 不变）
- **does not supersede:** ADR 0004 / 0006 的 **本地-only** 边界（禁止 npm/git、`~/.pi`、`pi install`）
- **feature contract:** [`docs/features/agent_engine_extensions_v1.md`](../../features/agent_engine_extensions_v1.md) **frozen v0.2.0**

## Context

P3（ADR 0006）已同构落地 coding-agent package-manager **本地子集**：`capability_packages/` 发现/解析/加载，extension 面实质为 **注册 `AgentTool`（及 skill/prompt 收集）**。

上游完整 extension 子系统（`coding-agent/src/core/extensions/{types,loader,runner,wrapper}`）还包含：

- `ExtensionAPI.on(event)` 生命周期事件；
- `ExtensionRunner` dispatch 与 handler 返回值合并；
- `registerTool` 及 tool wrap；
- 与 agent/session loop 的 emit 接线。

本仓现状：

- package 可挂 tool，**不能**以 extension 方式改 system/payload/compact（Reasonix 类能力无法 package 化）；
- `CapabilityRegisterApi` 仅为上游 `ExtensionAPI` 的临时薄子集；
- Agent 上另有 host 级 `on_payload` / `transform_context` 等，与上游 extension 事件 **平行**。

产品定位仍是：**agent 核心引擎**（非 coding TUI）。需要在 **不** 恢复 install/TUI 的前提下，把 **引擎相关** extension 运行时按上游同构补齐。

## Decision

### D-EX1 — 规范源与同构对象

**P3.1** 规范源：

`earendil-works/pi` **`main`** → `packages/coding-agent/src/core/extensions/**`  
（types / loader / runner / wrapper；及 host 侧 runner 绑定/emit 对照 `agent-session` 等 **引擎路径**）

实现方式：**TS→Python 同构翻译**（事件名、dispatch 语义、registerTool 形状）；不重设计平行 Hook 品牌。

**不是** 移植完整 coding-agent 产品（TUI、CLI、trust UX、settings 双 scope install）。

### D-EX2 — 落点（G3）

```text
packages/agent/src/earendil_works/pi_agent/extensions/
  # ← coding-agent/src/core/extensions/* 同构
```

Import：`earendil_works.pi_agent.extensions`（及子模块）。

- **禁止** 另起第二 agent 内核包冒充「完整 coding-agent」。
- 与现有 `package_manager/`（本地发现）协作：E2 下资源解析/extension 加载与上游同构；**install 通道仍 omit**（ADR 0006 D-PM3）。

### D-EX3 — 产品裁切 S-engine（feature §3）

| IN | OUT |
|----|-----|
| Engine 生命周期事件（feature §3.1 IN 表） | TUI / `ui.*` / theme / `input` / `user_bash` / `project_trust` |
| `registerTool`、runner、wrap tools | session 树事件：`session_before_switch|fork|tree`、`session_tree` |
| 本地 package 加载 + skills/prompts apply（SK2） | `resources_discover` |
| ExtensionContext **C-engine** 字段（feature §3.2） | 完整 `ExtensionUIContext`、CommandContext 的 fork/switch/navigate 等 |
| | npm/git/`pi install`/`~/.pi`（ADR 0006） |

OUT 项 **不出现在本仓公开 API**（禁止永久 no-op 假装完整 Pi）。

### D-EX4 — 与 P3 临时面的关系

| P3 现状 | P3.1 目标 |
|---------|-----------|
| `CapabilityRegisterApi.add_tool` | 上游对齐 **`registerTool`**（**M2**：无长期兼容层） |
| `apply_capability_report` 仅 merge tools | **AP3**：公开挂载对齐 `createExtensionRuntime` / `loadExtensions` / `ExtensionRunner` / `wrapRegisteredTools` 等；P3 apply **收敛**，禁止与 runner **双 SoT** |
| host `on_payload` / `transform_context` | **H1**：loop **仅** extension 事件；删除或废弃平行公共 host 钩子 |
| skills/prompts 多进 report 未完整 apply | **SK2**：load **且** apply 到 harness |

现有 search 等 capability 包：业务逻辑不变；**仅** `register` 胶水改为 `registerTool`（M2）。

### D-EX5 — Host deltas（允许）

| Upstream | Python / 本仓 |
|----------|----------------|
| `.ts` + jiti | `.py` + importlib（已有） |
| 完整 TUI Session / UI | C-engine Context；无 `ui` |
| `ExtensionCommandContext` 会话树 UX | **omit**（与 OUT 事件一致） |
| IN 方法未接线 | **显式抛错**，禁止静默 no-op 成功 |

### D-EX6 — 实现顺序与文档

1. 本 ADR + 架构契约 **0.3.4**（先于宣称实现 done）。  
2. Feature 边界已 **frozen**：`agent-engine-extensions-v1` v0.2.0。  
3. 实现计划：`docs/plans/P3_1_agent_engine_extensions.md`。  
4. Roadmap 阶段：**P3.1**（`P3-extensions`）；**非** P4 业务能力。  
5. 验收：feature §10（AC1）。

## Consequences

1. P3「只能挂 tool」升为「可挂 engine extension」；Reasonix 类缓存可作为 **后续** capability package，不在本 ADR 交付。  
2. 体量主要在 `extensions/*` + Agent loop emit 接线；**不**扩大 install 面。  
3. 契约测试须继续 **禁止** npm/git/home install 路径；并校验 OUT 事件/UI 不进入公开 API。  
4. search feature 文档中 `api.add_tool` 描述须在 P3.1 落地后同步升版。

## Alternatives rejected

| 方案 | 原因 |
|------|------|
| 仅扩 `CapabilityRegisterApi` 几个 hook 名、不 port runner | 非同构；易成第二套 API |
| 全文 coding-agent（TUI/install） | 产品非 coding TUI；与 D5/D22/ADR 0006 冲突 |
| 独立 `packages/coding_agent` 空壳产品包 | 无 TUI 目标；G3 噪音（feature P-b） |
| 保留 host 钩子与 extension 双路径（H2） | 顺序难测、双 SoT |
| `add_tool` 长期兼容层（M1） | 与「一次对齐上游」冲突 |

## Implementation pointer

- Feature：`docs/features/agent_engine_extensions_v1.md` **v0.2.0 frozen**  
- Plan：`docs/plans/P3_1_agent_engine_extensions.md`  
- Upstream：`vendor/earendil-works-pi/packages/coding-agent/src/core/extensions/`  
