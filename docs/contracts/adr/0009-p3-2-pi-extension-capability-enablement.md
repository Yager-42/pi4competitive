# ADR 0009: P3.2 — Pi extension capability enablement

- **status:** accepted
- **date:** 2026-07-26
- **contract_version_before:** 0.3.4
- **contract_version_after:** 0.3.5
- **extends:** ADR 0008（P3.1 S-engine extension runtime）
- **does not supersede:** ADR 0006 的 local-only package 边界，或 ADR 0008 的无 TUI / 无平行 hook / 无第二内核边界
- **consumer feature:** `reasonix-prefix-cache-v1`（**frozen** v0.1.0）

## Context

P3.1 已完成 `pi_agent.extensions` 的 S-engine baseline：local package 能注册工具并使用既有 engine events。后续 Reasonix 式 prefix-cache capability 证明，仅靠 package handler 无法诚实完成两件事：

1. `packages/ai` 需要补回 upstream Pi 已有的 cache transport / usage parsing 语义；
2. 真实 append-only history rewrite 需要 provider-neutral 的 `CompactionPlan` transaction，而不是 package 直接写 Agent/session。

把这项工作归入 P4 `competitive_app` 会错误地把 Pi engine enablement 与业务 workflow/domain 绑定；把已完成 P3.1 改写为“未完成”又会抹掉其已验收的 runtime baseline。原 D16 没有 P3.2，故阶段顺序需正式演进。

## Decision

### D-P32-1 — 新的串行 Pi 阶段

实现顺序变为：

```text
P1 → P2 → P3 → P3.1 → P3.2 → P4
```

**P3.2** 名为 **Pi extension capability enablement**。它只在 P3.1 done 后实施，P4 `competitive_app` 在 P3.2 exit gate 前不得成为下一阶段主路径。

### D-P32-2 — 受限职责

P3.2 可包含且仅可包含：

| 层 | 允许职责 |
|---|---|
| `packages/ai` | 对照 upstream `main` 补齐已存在的 provider cache request / usage 语义与测试 |
| `packages/agent` | 为既有 extension lifecycle 提供最小、provider-neutral 的 validated `CompactionPlan` transaction / checkpoint；不得另造公开 hook |
| `capability_packages/reasonix_prefix_cache` | Reasonix policy、prefix diagnostics、status tool 与已有 event consumer |

Reasonix-specific threshold、summary instruction、DeepSeek/provider business policy、tool-result repair、UI/TUI、boot/environment product runtime 均不得进入 `packages/ai` 或 `packages/agent`。

### D-P32-3 — 现有 extension 路径唯一

P3.2 consumer 只能通过 ADR 0008 的 `ExtensionRunner` / `registerTool` / IN events 接入。不得新增 `on_cache`、`on_prompt_snapshot`、平行 payload/context hook、第二 agent loop 或跨进程 Reasonix runtime。

### D-P32-4 — 文档与门禁

实施前必须：

1. freeze P3.2 consumer feature；
2. 将 `agent-engine-extensions-v1` 升为版本化 P3.2 delta，并增补 `P3_1_agent_engine_extensions` plan delta；
3. 为 upstream `packages/ai` parity、generic bridge、local consumer 分别保留可重复门禁；
4. 验证 Reasonix 与既有 search capability packages 同载时无 tool collision / lifecycle 冲突。

## Consequences

1. P3.1 保持已完成、可复核的 S-engine baseline；P3.2 是其后的受限 consumer-enable stage。
2. P4 保持 `competitive_app` / DDD / workflow 阶段，不承担 Pi engine 改动。
3. D16、roadmap、术语及阶段门禁随 contract 0.3.5 同步更新。
4. 仍禁止 npm/git/home discovery、完整 coding-agent 产品、TUI、第二内核与 Reasonix policy core leakage。

## Alternatives rejected

| 方案 | 原因 |
|---|---|
| 归入 P4 App | 错置 Pi adapter / generic extension bridge 所有权；把非 domain 工作与业务 workflow 耦合 |
| 回写 P3.1 为未完成 | 已完成 baseline 与新的 consumer-enable 工作混淆，失去已验收边界 |
| package-only / 零核心改动 | 无法真实满足 append-only rewrite B；会把 H0 观测伪装成实现 |
| 完整移植 Reasonix host | 违反本仓非 coding TUI / 单 Pi 内核 / 最小 host-delta 边界 |

## Implementation pointer

- Consumer feature: [`reasonix_prefix_cache_v1.md`](../../features/reasonix_prefix_cache_v1.md) **v0.1.0 frozen**
- Runtime baseline: [`agent_engine_extensions_v1.md`](../../features/agent_engine_extensions_v1.md)
- Roadmap: [`ROADMAP.md`](../../ROADMAP.md)
- Plan: [`P3_2_pi_extension_capability_enablement.md`](../../plans/P3_2_pi_extension_capability_enablement.md) **v0.1.1**
