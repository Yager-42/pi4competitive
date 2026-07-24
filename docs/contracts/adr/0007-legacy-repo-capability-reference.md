# ADR 0007: 钉死 P4 能力参考旧仓身份（D12）

- status: accepted
- date: 2026-07-23
- contract_version_before: 0.3.2
- contract_version_after: 0.3.3

## Context

契约 **D12** 已规定「旧仓 = 能力参考；禁止抄旧仓当 Pi 父本」，**Roadmap §4** 也写「旧仓 = 能力参考，非 1:1 复刻清单」。  
但旧仓的**仓库身份**（远程 URL / 本地检出约定）未写入契约，agent 只能靠并排目录与 `.env.example` 注释推断，易与上游 `earendil-works/pi` 混淆。

P1–P3 已完成；P4 `competitive_app` 开工前须可稳定指向业务参考源。

## Decision

1. **旧仓身份（binding）**
   | 项 | 值 |
   |----|-----|
   | 产品/仓库名 | **CompetitorLens** 旧实现 / **`competitive-agent`** |
   | 远程（权威） | **https://github.com/xj120/competitive-agent** |
   | 本地约定 | 与本仓 **`pi4competitive` 并排检出** 的 `competitive-agent/`（本机常见：`…/revive/competitive-agent`） |
   | 主要参考树 | `backend/workflows/competitive/`、`backend/` 业务/API/搜抓与 packages 面；**非** `backend/agent/` 作 Pi 父本 |

2. **角色不变（D12）**
   - 旧仓 **只** 作 P4 业务能力 / workflow / 领域形状的 **能力参考**。
   - **禁止** 以旧仓 agent loop/session 替代或分叉 `packages/ai|agent`（Pi 父本仍仅为 `earendil-works/pi` **main**）。
   - **禁止** 把旧仓清单当作必须 1:1 复刻的 backlog（Roadmap §4 仍管业务冻结）。

3. **契约落点**
   - 决策摘要 **D12** 补身份列/说明。
   - §1.2 旁或术语表区分 **上游 main** vs **旧仓**。
   - Roadmap §4 步骤 4 写明同一远程，避免双源漂移。

## Consequences

- P4 / grill / FEATURES 草稿可稳定引用旧仓路径与远程。
- 新 agent 会话不再把 `competitive-agent` 误当成 Pi upstream。
- 若旧仓迁址或改名：升契约版本 + 改本 ADR 指针（或 supersede）。

## Alternatives rejected

| 方案 | 原因 |
|------|------|
| 继续只写「旧仓」不写 URL | 身份不可检索，重复误判 |
| 把旧仓 submodule 进本仓 | 非必需；参考即可，避免绑定业务快照 |
| 旧仓当 Pi 父本 | 违反 D12 / D14 |
| 仅写本机绝对路径 | 不可移植；远程为权威，本地为约定 |
