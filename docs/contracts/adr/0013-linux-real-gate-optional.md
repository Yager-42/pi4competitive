# ADR 0013: P3.3 — Linux real-enforcement gate 改为可选项

- **status:** accepted
- **date:** 2026-08-03
- **contract_version_before:** 0.3.9
- **contract_version_after:** 0.3.10
- **supersedes:** ADR 0012 D-NSBX2 中「Linux 与 macOS 都是正式支持平台、必须通过相同行为测试」的等权 gate 表述，以及 D-NSBX10 gate 2「Linux amd64 real enforcement」作为 P3.3 关闭 blocker 的强制属性
- **preserves from ADR 0012:** native-only production 数据面（D-NSBX1）、macOS 正式 gate（D-NSBX2 的 macOS 半边）、三 frozen 父本（D-NSBX3）、universal executor（D-NSBX4）、所有权（D-NSBX5）、policy/network/secrets（D-NSBX6）、per-call 隔离（D-NSBX7）、readiness fail-closed（D-NSBX8）、transplant/license（D-NSBX9）、offline contract/port parity 与 macOS real enforcement/App e2e/baseline 门禁（D-NSBX10 其余）
- **feature contract:** [`agent_tool_native_sandbox_v1.md`](../../features/agent_tool_native_sandbox_v1.md) **v0.2.2**（gate 措辞按本 ADR 修订）
- **implementation plan:** [`P3_3_agent_tool_native_sandbox.md`](../../plans/P3_3_agent_tool_native_sandbox.md) **v0.1.4 active**；[`G0 map`](../../plans/P3_3_native_sandbox_G0_map.md) v0.1.0（执行注记更新）

## Context

ADR 0012 要求 P3.3 关闭前 Linux amd64 与 arm64 macOS 都通过真实 enforcement gate（S1–S9）。当前唯一可用开发/验收主机是 arm64 macOS（Darwin 24.3.0，Apple M4）：

- macOS 真实 gate 可直接执行：`sandbox-exec` 存在，Phase C 的 `test_broker.py` 已有真实 Seatbelt e2e；
- Linux bubblewrap/seccomp 真实执行需要 Linux amd64 主机或 CI，项目当前没有该基础设施，也不保证未来提供；
- Linux 侧的**离线**移植与 parity 已完整且为 binding：`native/srt/{linux,seccomp}.py`、apply-seccomp 二进制供应链（G0 §5）、O11–O15 golden 测试全部通过。

把 Linux 真实门禁作为硬性 exit blocker，会让 P3.3 在没有该基础设施的情况下永远无法关闭，而 macOS 侧全部真实行为验证已可执行。用户决定：V2（Linux real enforcement）改为可选项，V3（macOS real enforcement）与 V4（审计/收尾）必须完成。

这不是把 Linux 降级为“支持但未验证”：任何 Linux production 部署声明仍以 Linux real suite 通过为前提；本 ADR 只改变 P3.3 **关闭** 的阻塞条件。

## Decision

### D-NLX1 — Linux real enforcement（V2）为可选项

- Linux amd64 上的 S1–S9 真实 enforcement/e2e 套件（plan V2）**保留编写与运行契约**：在 Linux amd64 主机/CI 可用时运行，套件本身不得在非 Linux 主机上作为离线测试强制运行（沿用 host-gated skip）；
- **不阻塞 P3.3 closeout**：P3.3 可在 macOS gate + offline parity + V4 审计全绿后关闭；
- **任何 production Linux 部署声明前必须先通过该套件**；未通过前不得宣称 Linux production 支持已验证。

### D-NLX2 — macOS real enforcement（V3）为正式必过 gate

- arm64 macOS 的 S1–S9 真实 enforcement（Seatbelt profile 文件系统/网络判定）与 App e2e（parallel、timeout/abort/cleanup、approval 判定）必须在本机真实执行通过；
- macOS 不因“另一平台可选项”而获得任何降级：fail-closed、no-host-fallback 行为与 offline parity 要求不变。

### D-NLX3 — offline gate 全平台 binding

- O1–O22 与 V1 离线 parity 在所有平台 binding，不随本 ADR 改变；
- Linux 离线 golden（SRT linux/seccomp、apply-seccomp 供应链校验）保持 binding，继续作为 Linux 路径的唯一可执行证据，直到可选 real suite 补上。

### D-NLX4 — 残余风险记录

- Linux production 真实行为（bubblewrap mount/network/PID namespace 嵌套、seccomp 生效）在可选套件通过前**未验证**；
- feature §11 与 plan §5.2 同步记录该风险；roadmap 完成标准改为“Linux real gate 可选；macOS real gate 必过”。

## Consequences

1. P3.3 关闭条件变为：offline parity（V1）+ macOS real enforcement/e2e（V3）+ 资源 baseline 与文档/license/CodeGraph 审计（V4）+ Docker production 代码删除（已完成）。
2. Linux 真实验证变成按需执行：出现 Linux 主机/CI 时运行 V2 套件，其结果作为 Linux production 部署的前提证据。
3. 不修改任何 production 代码：这是门禁/文档决策；native Linux 路径实现与离线测试原样保留。
4. 残余风险显式化：Linux 未验证状态写入 feature/plan/roadmap，不暗示已完成。

## Alternatives rejected

| Alternative | Reason |
|-------------|--------|
| 保持 Linux real gate 为硬性 blocker | 项目无 Linux 主机/CI，P3.3 永久无法关闭；macOS 侧已验证行为被无谓阻塞 |
| 取消 Linux 支持声明 | 与 frozen 三父本（erichll Linux 路径）和既有离线移植不符；Linux 路径实现已完成，只是缺真实执行证据 |
| 在 macOS 上以 stub 冒充 Linux real gate | 违反“真实 enforcement”语义与 no-fabrication 原则 |

## Implementation pointer

- Feature: [`agent_tool_native_sandbox_v1.md`](../../features/agent_tool_native_sandbox_v1.md) **v0.2.2**
- Plan: [`P3_3_agent_tool_native_sandbox.md`](../../plans/P3_3_agent_tool_native_sandbox.md) **v0.1.4 active**；G0 map v0.1.0（执行注记）
- 被修订决策的原始 ADR: [`0012-native-agent-tool-sandbox-runtime.md`](0012-native-agent-tool-sandbox-runtime.md)
