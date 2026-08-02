# ADR 0012: P3.3 — native AgentTool sandbox runtime

- **status:** accepted
- **date:** 2026-08-02
- **contract_version_before:** 0.3.8
- **contract_version_after:** 0.3.9
- **supersedes:** ADR 0011 + 0011-A 的 Docker-specific provider/backend/runtime/image/lifecycle/resource/live-gate 决策
- **preserves from ADR 0011:** provider-neutral `AgentToolExecutor`、universal production coverage、approved target registry、`agent-tool-rpc.v1`、parent scope/workspace、no-host-fallback、Pi/App 双层所有权
- **feature contract:** [`agent_tool_native_sandbox_v1.md`](../../features/agent_tool_native_sandbox_v1.md) **frozen v0.2.1，G1–G10 resolved，G0 complete**
- **implementation plan:** [`P3_3_agent_tool_native_sandbox.md`](../../plans/P3_3_agent_tool_native_sandbox.md) **v0.1.1 active**；[`G0 map`](../../plans/P3_3_native_sandbox_G0_map.md) v0.1.0

## Context

ADR 0011 建立了正确的通用执行收口：`competitive_app` production 的所有 `AgentTool.execute()` 经过 `AgentToolExecutor`，由 approved registry 绑定可重新 import 的 Python target，通过严格 JSON worker bridge 执行，失败不得回退宿主。该部分已经实现并保留。

其 Docker/AIO 数据面实测成本过高：

| Metric | Current Docker/AIO evidence |
|--------|-----------------------------|
| Derived image | about 12.1 GB |
| Cold scope acquire | about 1.386 s |
| Warm call | about 35–60 ms |
| Idle scope | about 332 MiB RSS / 31 PIDs |
| Startup block I/O | about 231 MB |

用户明确选择以 `@erichll/pi-sandbox@0.4.2` 为父本，将其 Linux bubblewrap/seccomp 与 macOS Seatbelt 路径等价翻译到 Python，并一并移植其依赖的 Sandbox Runtime 和 `pi-auto-review` 审批核心。Docker 不作为 provider、fallback 或兼容后端保留。

当前架构约束的含义是能力归属与依赖方向：通用 Agent 能力进入 `packages/agent`，App sandbox IO/组合进入 `competitive_app` adapter/wiring，Domain 保持纯净；不是继续保留将被本 ADR supersede 的 Docker-specific 决策。

## Decision

### D-NSBX1 — native-only production 数据面

生产拓扑改为：

```text
FastAPI / Pi Agent / Session（唯一 Host Python 控制面）
  -> AgentToolExecutor
  -> SandboxToolExecutor
  -> NativeSandboxProvider
  -> per-call Python broker + Python SRT port
       -> Linux: bubblewrap + apply-seccomp
       -> macOS: Seatbelt sandbox-exec
       -> approved Python AgentTool worker
```

Native provider 是唯一 production backend。不得提供 Docker/native switch、Docker fallback、Host IPC、LocalRuntime、宿主 subprocess/FS fallback 或 `enabled=false`。

迁移 gate 通过后删除 Docker provider/backend/runtime、AIO image、`agent-sandbox` SDK 和相关 production config。ADR 0011/0011-A 与旧 feature/plan仅作为历史记录保留。

### D-NSBX2 — Linux 与 macOS 都是正式支持平台

Linux 和 macOS 都必须通过相同的 filesystem、network、approval、timeout、abort、cleanup、parallel 和 fail-closed 行为测试：

- Linux 等价翻译 upstream bubblewrap mount/network/PID namespace 与 seccomp 路径；
- macOS 等价翻译 upstream Seatbelt profile 与 sandbox-exec 路径；
- 平台使用不同内核原语不构成 macOS 绕过或宿主 fallback 的理由；
- unsupported platform 或所需 helper/OS capability 不可用时 startup fail closed。

### D-NSBX3 — 三个 frozen Python 移植父本

| Role | Frozen source | Rule |
|------|---------------|------|
| Pi sandbox adapter/security semantics | `@erichll/pi-sandbox@0.4.2` / `erichll/pi-packages@10c8eeb8269ee478ff7383c7e6139301aa9665f9` | 能映射即 COPY-semantics，确有 host delta 才 ADAPT |
| OS isolation | `@anthropic-ai/sandbox-runtime@0.0.67` | 只移植 erichll 实际使用的 manager/Linux/macOS/seccomp/proxy/process 子集 |
| Boundary approval | `@erichll/pi-auto-review@0.3.2` / 同一 frozen SHA | 移植 hard deny、model review、exact hash、one-shot grant、circuit breaker、evidence bounds/redaction |

TypeScript/JavaScript 被行为等价翻译为 Python；production 不使用 Node/npm runtime。后续升级必须逐版本审查 source/security/behavior delta，不跟随 floating latest。

### D-NSBX4 — 保留 universal AgentTool execution contract

以下 ADR 0011 host-neutral 行为继续 binding：

1. production main、dynamic、extension、Harness、resume、ephemeral sub-agent 的每次 `AgentTool.execute()` 经过同一 executor；
2. `packages/agent` 保留 provider-neutral executor/Direct parity/target metadata，不 import App/native sandbox；
3. Host approved registry 是 tool name 到 `module + qualname` 的唯一可信绑定；
4. worker 只执行 approved module-level four-argument async callable；
5. `agent-tool-rpc.v1` 保持 JSON-only request、ordered update、single terminal result/error；
6. parent session scope/workspace 与 ephemeral inheritance 保持；
7. Pi validation、extension events、AgentToolResult 和 JSONL 顺序不变。

### D-NSBX5 — Pi/App/DDD 所有权

| Layer | Ownership |
|-------|-----------|
| `packages/agent` | provider-neutral `AgentToolExecutor`、Direct parity、target metadata、executor/scope propagation；generic boundary-approval broker/service contract（无 App/OS policy） |
| `capability_packages/pi_auto_review` | `pi-auto-review@0.3.2` model reviewer、hard-deny policy、grants、circuit breaker、bounded evidence；作为 Python Pi local capability/extension |
| `competitive_app.adapter.out.sandbox` | native provider/runtime/SRT broker、OS/filesystem/network process IO、sandbox trap/approval adapter、worker transport |
| `competitive_app.wiring` / lifespan | 从 Agent extension runtime 取得 boundary broker 并注入 sandbox、trusted App sandbox config、readiness、shutdown |
| `competitive_app.domain` | 无 sandbox/subprocess/filesystem/network/approval IO |
| `packages/ai` | 仅提供既有 model API；不拥有 sandbox/approval policy |

`pi-auto-review` reviewer 复用 `earendil_works.pi_ai` 和当前 model registry，不引入第二 LLM framework。通用 broker/service seam 属 Pi Agent；具体 reviewer policy 属 local capability，不焊入 Pi core；OS trap 与执行许可的适配属 App sandbox adapter。

### D-NSBX6 — policy、network 与 secrets

1. tool `cwd` 是 `data/sandboxes/<scope-id>`，不是 repo root；workspace 是唯一可写业务路径；
2. Python runtime、approved tool bundle、worker、manifest 和 helper 来自 startup 验证的只读安装路径；
3. Host home、App source/config、`.git`、`.env`、session JSONL、SQLite、其他 scope 与 Docker socket 不可见；
4. 保留 erichll workspace secret deny-write policy；
5. network 默认 deny；unmatched public `hostname:port` 必须经 Python approval broker；
6. DNS 任一解析结果为 private/loopback/link-local/multicast/metadata 类地址即 deny；
7. broker/reviewer 缺失、异常、超时、defer 或 grant mismatch/expired/consumed 均 deny；
8. 只在成功消费 exact one-shot grant 后放行该连接；
9. worker 沿用当前七项 search provider env allowlist，不继承 full Host env；approval model credential 留 Host。

### D-NSBX7 — per-call isolation、abort 与资源边界

每次调用拥有独立 Python broker、SRT manager、proxy 和 target process tree；同 scope 并行调用共享 workspace，但使用独立进程边界。scope idle 时不保留 broker、worker 或 per-scope proxy。

保持 erichll 的 wall timeout、abort、detached process-group kill 和 finally cleanup，并保持当前 RPC payload/frame/update/result size limit。scope abort 终止该 scope 的全部 active brokers。

本版本不新增 erichll/SRT 不具备的 cgroup 或 macOS resource monitor，因此不承诺 Docker 原有 CPU/memory/PID/filesystem-size hard quota。这是明确接受的残余风险；未来 quota 需独立 feature/ADR。

### D-NSBX8 — startup/readiness 与 fail closed

lifespan 在对外服务前真实验证：

- trusted config 严格解析，unknown key/malformed value 拒绝；
- platform/helper/SRT broker 可用；
- approved manifest 与 Host registry 一致；
- workspace write allow、Host home read deny；
- network default deny；
- worker canary、abort 和 cleanup 无 orphan。

任何失败阻止 App startup 并清理 partial init。正常 dev server 与 production 相同；tests 仍只能通过显式 Python DI 注入 Direct/mock/spy。

### D-NSBX9 — transplant 与许可证

implementation plan 必须逐文件记录 `COPY / ADAPT / OMIT / NEW-HOST`。直接复制或实质改编保留 source package/version/path、commit、license 和 host delta：

- `pi-sandbox` Apache-2.0；
- Sandbox Runtime Apache-2.0；
- `pi-auto-review` MIT。

明确 OMIT：erichll Pi extension registration、内建 subagent tool、Host IPC、coding TUI auto-confirm/toast/`/approve` UI、Windows、SRT 通用 CLI/AWS signing/未使用 credential rewriting。OMIT 是因为当前架构已有 universal executor/sub-agent ownership 或没有对应 UI/product surface，不是任意重写许可。

### D-NSBX10 — verification 与阶段门禁

P3.3 重新保持 `in_progress`。旧 Docker F3 外部 Linux 证据不再是 exit blocker；新的 native gate 取代它：

1. offline contract/port parity；
2. Linux amd64 real enforcement；
3. arm64 macOS real enforcement；
4. universal App e2e、network approval、parallel、abort/cleanup；
5. 同机 cold/steady/parallel/idle/disk baseline comparison。

性能比较必须诚实记录，但不设置会驱动偏离 frozen per-call broker 安全模型的人为 SLA。所有 native gate green、Docker production code/dependencies 删除、文档与 license 审计完成后才能关闭 P3.3。

## Consequences

1. 移除 12.1 GB AIO image、Docker daemon/SDK startup dependency和每 scope idle container。
2. 每次调用仍有 broker/SRT/Python worker 启动开销；steady latency 可能高于 warm Docker，必须实测报告。
3. Linux/macOS 都能 production 使用，但内核隔离原语不同；不得宣称二者内部机制等价。
4. model-backed network approval 增加一次 Host LLM policy path；failure mode 固定 deny。
5. 缺少 Docker hard quotas 是接受的 residual risk。
6. Python SRT port 形成需要跟踪 upstream security fixes 的维护责任。

## Alternatives rejected

| Alternative | Reason |
|-------------|--------|
| 保留 Docker 作 fallback/strong mode | 用户明确 native-only；双 backend 增加漂移并削弱 fail-closed |
| Python 直接调用 SRT Node CLI | 违反 production 无 Node/npm runtime，且增加 per-call CLI 开销 |
| 只翻译 erichll adapter，不移植 SRT | adapter 本身不提供 OS isolation |
| 只 sandbox Bash | 低于当前 universal AgentTool coverage，可被非 Bash tools 绕过 |
| 把 native policy 放进 `packages/agent` | 污染 Pi provider-neutral core，违反 Pi/App/DDD 所有权 |
| Host IPC 审批后重试 | 执行发生在 OS sandbox 外，违反 no-host-fallback |
| 本次顺便重写 persistent broker/cgroup | 偏离“应抄尽抄”的 frozen 父本，扩大 feature |

## Implementation pointer

- Feature: [`agent_tool_native_sandbox_v1.md`](../../features/agent_tool_native_sandbox_v1.md) frozen v0.2.1
- Plan: [`P3_3_agent_tool_native_sandbox.md`](../../plans/P3_3_agent_tool_native_sandbox.md) v0.1.1 active；G0 map v0.1.0 complete
- Historical Docker ADR: [`0011-agent-tool-sandbox-runtime.md`](0011-agent-tool-sandbox-runtime.md)
