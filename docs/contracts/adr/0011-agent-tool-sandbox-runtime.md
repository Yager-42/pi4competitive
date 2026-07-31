# ADR 0011: P3.3 — production AgentTool Docker sandbox execution

- **status:** accepted
- **date:** 2026-07-31
- **contract_version_before:** 0.3.6
- **contract_version_after:** 0.3.7
- **extends:** ADR 0008（P3.1 extension runtime）与 ADR 0009（P3.2 capability enablement）
- **does not supersede:** Pi `main` 同构基线、唯一 agent 内核、local-only capability package、DDD/Domain 无 IO、JSONL/SOCM/SQLite SoT 边界
- **feature contract:** [`agent_tool_sandbox_v1.md`](../../features/agent_tool_sandbox_v1.md) **frozen v0.1.31，G1–G30 resolved**
- **sandbox code parent:** [`HezaoHezao/poirot`](https://github.com/HezaoHezao/poirot/tree/86bf279ad90c180f0ba696755620dd7d6661465e) @ `86bf279ad90c180f0ba696755620dd7d6661465e`

> 本 ADR 已 accepted，并由架构契约 0.3.7、Roadmap P3.3 与 frozen feature v0.1.31 同步生效。implementation plan v0.1.0 已建立；运行时代码只能按 plan 推进。

## Context

当前 Pi 工具执行点在宿主进程直接调用：

```python
result = await prepared["tool"].execute(
    prepared["toolCall"]["id"],
    prepared["args"],
    signal,
    on_update,
)
```

模型生成的参数已经过 schema validation，但 `execute()` 仍与 FastAPI、Pi Agent、LLM、session 和 App Process Manager 共用宿主进程及文件/环境边界。当前 production search tools 会访问网络；后续本地 capability 也可能读写文件或执行命令。仅靠 Python wrapper、路径检查或宿主 subprocess 不能形成操作系统级隔离。

Pi upstream `main` 没有 `ToolExecutor` seam；直接加入 executor 是必须列名的 Python host delta。另一方面，Poirot frozen SHA 已实现可移植的 sandbox facade、provider/runtime/backend、Docker lifecycle、path/guard/audit、warm pool 与测试，但其真实集成只把六个专用 façade tools 放入 sandbox，其他工具按名字 passthrough。它不是任意 Python `AgentTool.execute()` remote executor。

因此需要同时满足两项约束：

1. `competitive_app` production 的每次 `AgentTool.execute()` 都进入 Docker，且失败时不回退宿主；
2. 继续保持唯一 Pi 控制面和现有架构依赖方向，模块契约对得上时优先移植 Poirot，而不是另造 sandbox 架构。

## Decision

### D-SBX1 — 新增串行阶段 P3.3

实现顺序变为：

```text
P1 → P2 → P3 → P3.1 → P3.2 → P3.3 AgentTool sandbox → continue P4
```

P3.3 统一交付 Pi executor seam、App sandbox adapter、production wiring 与真实 Docker 门禁。P4 已有实现不回退，但 P3.3 exit gate 关闭前，不继续扩大依赖 `AgentTool` 的 P4 业务面。只完成 Pi 或 App 任一侧均不得宣称 P3.3 完成。

### D-SBX2 — 单控制面、容器工具数据面

现有 D1“单进程 Python”澄清为**单一 Python 控制面**：

```text
FastAPI / competitive_app
  → Pi Agent loop（宿主）
  → AgentToolExecutor
  → Docker sandbox worker（工具执行数据面）
```

宿主继续拥有：LLM、Agent loop、tool schema validation、`prepareArguments`、extension lifecycle、Session/JSONL、SOCM、SQLite 与 Application Process Manager。Docker worker 只重新 import 一个已批准的 Python tool target 并执行其 `execute()`；不得包含第二 Agent loop、LLM provider、FastAPI、workflow 或 session runtime。

容器 worker 是隔离基础设施进程，不反转“唯一 agent 内核 = `packages/agent`”或“Node 非运行时依赖”。

### D-SBX3 — Pi/App 双层所有权

| 层 | 唯一职责 |
|----|----------|
| `packages/agent` | provider-neutral `AgentToolExecutor` contract、upstream-compatible `DirectToolExecutor`、execution target metadata、executor/scope 传播及既有事件顺序 |
| `competitive_app.adapter.out.sandbox` | Poirot sandbox facade、contracts、provider/runtime/backend、Docker lifecycle、worker transport |
| `competitive_app.wiring` / lifespan | production Docker composition、eager readiness、scope binding、shutdown |
| `competitive_app.domain` | 无 Docker/SDK/文件/网络 IO；边界不变 |

`packages/agent` 不 import Docker、`agent-sandbox` 或 `competitive_app`。Docker policy 不进入 Pi core；App adapter 不拥有 LLM、Agent state、workflow policy 或 tool schema validation。

`DirectToolExecutor` 只作为 `pi_agent` standalone 默认值和显式测试依赖，保持 upstream direct-call parity；它不是 `competitive_app` production fallback。

### D-SBX4 — production universal、Docker-only、fail closed

1. `competitive_app` production 中，main Agent、动态 tool set、extension tool、harness tool、resume 与 ephemeral sub-agent 的每次 `AgentTool.execute()` 都必须经过同一 sandbox executor；不得按 tool/provider/package/name bypass。
2. production 只允许 Docker。Docker daemon、pinned image、provider、target、protocol 或 readiness 不可用时 fail closed；不得降级到 Direct、LocalRuntime、宿主 subprocess/FS。
3. FastAPI lifespan 在 `yield` 前完成 Docker、image、worker build/protocol handshake 与真实 canary；失败阻止 App 启动并清理 partial init。
4. rollout 单位是应用版本；不提供 `enabled/provider`、kill switch、shadow/dual、百分比/session/tool gate 或进程内回退。操作回退只使用既有部署版本回滚。
5. App tests 仅可通过 Python 参数显式注入 Direct 或 test-local mock/spy；正常 dev server 与 production 一样要求 Docker。

### D-SBX5 — session scope、workspace 与 provider lifecycle

1. 一个 parent session 对应一个稳定 sandbox scope；ephemeral sub-agent 继承 parent scope/workspace，不使用临时 session id。当前无 auth，tenant identity 固定为 `local-default`。
2. scope id 适配 Poirot deterministic SHA-256 recipe，使用 version + tenant + parent session，并保留完整 64 位 lowercase hex。
3. workspace 唯一 bind mount：`data/sandboxes/<scope-id>` → `/mnt/poirot/user-data` rw。代码与依赖 baked into image；repo、`.git`、`.env`、DB、sessions、home、Docker socket 及其他 host path 不挂载。
4. workspace 跟随 parent session 生命周期：completed/failed/aborted/restart 保留，resume 复用，显式 task delete 随 session cascade 删除；container idle/shutdown 不删除 workspace。
5. `COPY/ADAPT` Poirot 三层 acquire、same-ID warm reclaim、soft replicas、orphan reconciliation、idle cleanup、release 与 shutdown。一个最外层 parent Agent run lazy acquire、`finally` release 一次；不新增 per-call lease/refcount。
6. abort 销毁整个 scope container 并 bounded verify stopped，终止同 scope 全部并行 worker；不新增 per-process PID/kill RPC。

### D-SBX6 — approved target 与最小 JSON worker bridge

Production target 必须是 worker image 内可由 `module + qualname` 重新 import 的 module-level `async def`，并与 App startup 构建的 immutable approved registry 完全匹配。closure、lambda、partial、bound method、callable object、动态 source/eval、同步函数及需要第五参数 `ExtensionContext` 的 tool 在 production startup 拒绝；standalone Direct parity 不受影响。

Poirot 不存在 universal AgentTool RPC。为保持 Pi tool contract，允许最小 `NEW-HOST`：

- protocol 固定为 `agent-tool-rpc.v1`；
- request/update/result/error 使用 UTF-8 JSON；禁止 pickle、Python object/bytecode/source、`eval` 与 `repr()` fallback；
- worker 支持有序 partial update 和唯一 final；
- 同 scope parallel tool 使用同一 active container 内的独立 worker process 真并行，结果顺序仍由 Pi 决定；
- request、单 frame、累计 updates、final result 与 diagnostics 使用 feature G13/G24 的固定限额。

executor 调用仍位于既有 `beforeToolCall/tool_call` 与 `afterToolCall/tool_result` 之间，不改变 Pi validation、events、`AgentToolResult`、ToolResultMessage 或 JSONL 顺序。

### D-SBX7 — pinned AIO-derived Docker execution

保留 Poirot 的 AIO server/SDK transport，不另写 sandbox HTTP server；构建只增加 worker、approved capability code 与精确依赖的薄派生 multi-arch image：

```text
host SDK: agent-sandbox==0.0.30
AIO base: ghcr.io/agent-infra/sandbox@sha256:6328d7fd2f0ff0b4c147c3d05b3df1ce331f4a482eb6e550ecd64ed1fcf906e7
production image: pi4competitive-tool-worker@sha256:<build-output>
protocol: agent-tool-rpc.v1
```

Production 只接受 digest，不接受 `latest`；不在 container startup/tool call 时安装依赖，不挂 repo，不复制 FastAPI/Agent/LLM/workflow 控制面。

G18/G24 锁定的 non-root、read-only rootfs、capped tmpfs、cap-drop、no-new-privileges、effective seccomp、CPU/memory/PID/ulimit 与 loopback control port 均为 MUST，不提供关闭或 tuning 配置。AIO-derived image 若不能满足，必须重开 image 决策，不能降级 privileged/root/unconfined。

### D-SBX8 — Poirot parity 的 network、secret、error 与 SoT 边界

1. 网络复制 Poirot：control port 仅发布到 host loopback，container 使用 Docker 默认 bridge/egress；不新增 network/gateway/egress allowlist/private/metadata policy，也不使用 host network/显式 host-gateway。
2. container env 只继承当前七项 search provider 配置名；不传 LLM secret、全量 host env 或 `.env`，不新增 per-tool secret channel/rotation。
3. execute 期 sandbox acquire/runtime/worker/protocol/serialization/timeout/OOM/container-exit 异常按 Poirot/Pi catch-all 生成现有脱敏 error tool result；不新增 fatal taxonomy、强制 task failure、provider-wide circuit breaker 或 sandbox retry controller。Startup fail 与用户 abort 保持 D-SBX4/D-SBX5 独立语义。
4. Pi events + session JSONL 继续作为 tool call/result SoT；SOCM 与 SQLite 职责不变。只 `COPY` Poirot `AuditGuard` 与 provider lifecycle logger，不新增 audit store/API/span 或 args/result logging。

### D-SBX9 — transplant-first 与硬删除边界

Poirot frozen SHA 是 sandbox 基础设施代码父本，不替代 Pi `main` 作为 Agent 语义规范源。实施计划必须逐文件标记 `COPY / ADAPT / OMIT / NEW-HOST`：

- 职责、输入输出、控制流和生命周期能映射时优先近原样 `COPY`，只做 import/package/license 等机械调整；
- 宿主接口或 async/FastAPI/Pi 契约确有差异时才 `ADAPT`，并记录 host delta；
- Poirot 没有且本 ADR/feature 不强制的能力一律 `OMIT`；
- `NEW-HOST` 仅限 upstream 缺失的 executor seam、approved target/JSON worker bridge、derived image 及必要 wiring。

明确 `OMIT`：Poirot LangChain/LangGraph middleware、`SANDBOX_TOOL_NAMES` passthrough、LocalRuntime/LocalSandboxProvider/LocalSecurityGuard、任意 provider 反射配置、六个 product façade tools、`present_files`/ArtifactServer/store、K8s/E2B/remote backend、RunJournal/ActivityTracker、新 rollout 子系统、性能 SLA/benchmark/telemetry/tuning，以及本地 package install/npm/git/home/TUI 产品面。

直接复制或实质改编 Poirot 文件必须保留 frozen SHA/path、MIT copyright/license notice 与 host delta；`agent-sandbox` Apache-2.0 notice 同步保留。

### D-SBX10 — 文档与 exit gate

1. 架构契约升至 0.3.7，并同步 D1/D6/D9/D14/D16、逻辑架构、技术栈、质量门禁与术语。
2. Roadmap 增加 P3.3 及 exit gate；feature v0.1.31 冻结最终 Poirot module map 并链接 implementation plan。
3. feature frozen 后才能建立 implementation plan；plan 必须逐文件落实 transplant map，实施前重新记录当时 Pi `main` SHA。
4. offline contract/security tests 与真实 Linux amd64、Docker Desktop arm64 L1–L5 都是 P3.3 exit gate；live skip 不能关闭阶段。
5. Poirot 没有性能 SLA；只验证 readiness、真并行、warm reclaim 与真实功能，不新增 P50/P95/cold/warm/throughput 数值。

## Consequences

1. D1 从“所有执行都在单进程”澄清为“单一 Agent/LLM/App 控制面 + Docker tool 数据面”；仍无第二 Agent 内核。
2. `packages/agent` 增加一个列名 host delta，但 Direct executor 保持 upstream parity，Docker 依赖全部留在 App adapter。
3. `competitive_app` production 与正常 dev server 新增 Docker、pinned image 和 startup readiness 的硬依赖；不可用时不提供降级路径。
4. session workspace 可跨 container/restart 保留，带来磁盘增长残余风险；v1 不新增 aggregate quota，显式 task delete 负责回收。
5. Docker 默认 egress、scope 内共享七项 provider env、Docker operator inspect、kernel escape 与 cold-start overhead 是明确接受的残余风险，不作超出 Poirot 的安全或性能承诺。
6. 实现可大量复用 Poirot provider/lifecycle/path/guard/test 结构，但 universal AgentTool executor、JSON bridge 与 worker image 必须作为最小 host delta 单独审计。

## Alternatives rejected

| 方案 | 原因 |
|------|------|
| 把 FastAPI/Agent/LLM 整体放入每个 sandbox | 复制控制面、session 与 workflow，形成第二 Agent runtime |
| 只在 App startup 包装当前 tools | 动态 tool set、extension wrapper、resume 与 ephemeral sub-agent 可绕过 |
| 复制 Poirot tool-name middleware | Poirot 明确让非六工具 passthrough，违反 production universal 边界 |
| Docker policy 放进 `packages/agent` | 污染 provider-neutral Pi core 并反转依赖方向 |
| LocalRuntime/宿主 subprocess 作为 dev 或 fallback | 不是 OS 隔离，且会让 production fail-open |
| 每 tool call 一个 container | 破坏 session workspace 共享和 Poirot warm lifecycle，冷启动开销不必要 |
| 新写 sandbox HTTP server | AIO server/SDK 已覆盖 transport；增加第二套 server 无父本依据 |
| shadow/灰度/kill switch/host dual-run | Poirot 无此机制，且与 universal + no fallback 契约冲突 |
| 新增 egress/secret/audit/artifact/performance 子系统 | Poirot 无对应实现，用户未要求，现有架构与已锁定边界不强制 |

## Implementation pointer

- Feature：[`agent_tool_sandbox_v1.md`](../../features/agent_tool_sandbox_v1.md) **frozen v0.1.31**
- Poirot source：`HezaoHezao/poirot@86bf279ad90c180f0ba696755620dd7d6661465e`
- Pi forensics snapshot：`earendil-works/pi@471c3390fe015de9b7308fce0ada5bc7c3bb7d3c`（实施前重新对照 `main`）
- Plan：[`P3_3_agent_tool_sandbox.md`](../../plans/P3_3_agent_tool_sandbox.md) **v0.1.0 todo**
