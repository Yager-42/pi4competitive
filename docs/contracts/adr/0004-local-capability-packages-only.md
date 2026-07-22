# ADR 0004: 能力包仅本地目录加载

- status: accepted
- date: 2026-07-22
- contract_version_before: 0.2.6
- contract_version_after: 0.2.7

## Context

产品是 FastAPI 竞品服务 + Python 移植 Pi 基座，不是 coding TUI。无需 npm/git install、家目录自动发现或扩展商店。需要的是加载仓库内已实现的搜抓等能力包。

## Decision

1. 能力包根目录固定为仓库 `capability_packages/`。
2. 只加载该目录下子包；默认不远程下载、不扫 `~/.pi`。
3. 取消「阶段③ = coding-agent package-manager 全文同构」为必选项。
4. tool 运行语义仍由 `packages/agent`（main 同构）保证。

## Consequences

- 阶段③缩小为本地 loader。
- 能力包版本随 git 管理。

## Alternatives rejected

- 全文移植 package-manager + install
- 使用 `~/.pi/agent` 默认全局发现
