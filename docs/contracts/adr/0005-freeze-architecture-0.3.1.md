# ADR 0005: 冻结架构契约 v0.3.1

- status: accepted
- date: 2026-07-22
- contract_version_before: 0.3.1
- contract_version_after: 0.3.1 (freeze)

## Context

Grill 已收敛进程拓扑、Pi 移植范围与顺序、本地能力包、HTTP/async、配置与 Session 落盘等决策。

## Decision

将 `ARCHITECTURE_CONTRACT.md` **v0.3.1** 标为 **frozen baseline**。后续实现以该文档为准；任何修改决策摘要/分层/技术栈/移植策略须 ADR 并升契约版本。

## Consequences

- 可开始阶段① `packages/ai` 同构移植。
- 业务特性清单仍可另文，不阻塞基座开工。

## Alternatives rejected

- 继续开放 grill 推迟实现
