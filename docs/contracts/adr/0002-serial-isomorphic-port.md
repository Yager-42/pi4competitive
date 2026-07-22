# ADR 0002: 串行整包移植 + packages 与上游 monorepo 同构

- status: accepted
- date: 2026-07-22
- contract_version_before: 0.2.2
- contract_version_after: 0.2.3

## Context

移植范围含全量 `packages/ai`、C 档 `packages/agent`、coding-agent package 机制等。需决定实现顺序与仓库目录是否允许自创命名。

## Decision

1. 实现顺序 B：整份 ai 完成 → 整份 agent 完成 → coding 引进子集完成 → competitive_app。
2. 仓库使用 `packages/ai|agent|coding-agent` 与上游 monorepo 同构；禁止以 `pi_core`/`pi_ai`/`pi_packages` 作正式顶层路径。
3. 行为、模块边界、架构与 main 对齐，不仅公开 API 名称相似。

## Consequences

- 反馈周期长，需严格阶段门禁。
- 目录与上游对照简单，评审可文件级 diff 职责。

## Alternatives rejected

- 竖切半成品推进（A）
- App 先 mock 并行（C）
- 自创顶层包名布局
