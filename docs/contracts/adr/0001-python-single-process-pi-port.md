# ADR 0001: 单进程 Python 复刻 Pi 基座（废止双进程 Node Runtime）

- status: accepted
- date: 2026-07-22
- contract_version_before: 0.1.0
- contract_version_after: 0.2.0

## Context

v0.1 契约默认「Flask App + Node 官方 pi-agent-core 双进程 HTTP」。讨论后决定：不用双进程；用 Python 复刻 Pi 作为全应用基座；Package 机制来自 coding-agent 且实现上 TS→Python 对齐，扩展执行面仅 Python。

## Decision

1. 单进程 Python。
2. `pi_core`：对齐 agent-core + harness（C 档），官方 TS 为规范源。
3. `pi_packages`：对齐 coding-agent package 体系行为；tools/extensions 为 Python。
4. Competitive App 仍为 DDD + Flask 入站；过程执行器在 Application。
5. 废止 Node Pi Runtime 与 App 侧默认 HTTP PiGateway。

## Consequences

- 工程量集中在忠实移植，而非网关集成。
- 无法原样运行上游 TS 扩展文件。
- 上游 pi 升级需人工对照移植。

## Alternatives rejected

- 继续双进程官方 npm 包（违背单进程与「基座在 App 内」）。
- 自创简化 package/agent 架构（违背「不要自己想一套实现」）。
- 嵌 Node 执行 TS 扩展（违背单进程/A 选项）。
