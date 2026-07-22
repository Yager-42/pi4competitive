# ADR 0003: FastAPI 入站 + asyncio 内核

- status: accepted
- date: 2026-07-22
- contract_version_before: 0.2.4
- contract_version_after: 0.2.5

## Context

原契约默认 Flask。上游 Pi 为大量 async/stream；用户改用 FastAPI。

## Decision

1. HTTP 入站框架为 FastAPI（ASGI）。
2. `packages/ai` 与 `packages/agent` 公开 API 以 asyncio / async 迭代为主，对齐上游 Promise 与 async iterator 语义。
3. 废止 Flask 为默认。

## Consequences

- 与 D16 全量移植的流式 provider 一致。
- SSE/streaming 用 FastAPI/Starlette 原语。

## Alternatives rejected

- 保留 Flask + 同步内核
- sync+async 双公开面
