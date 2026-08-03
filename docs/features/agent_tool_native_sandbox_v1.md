# Feature 边界契约：agent-tool-native-sandbox-v1

| 字段 | 值 |
|------|-----|
| **feature_contract_version** | `0.2.2` |
| **status** | **frozen — G1–G10 resolved；ADR 0012/0013 accepted；implementation plan v0.1.6 complete（P3.3 done）；G0 complete** |
| **created** | 2026-08-02 |
| **updated** | 2026-08-03 |
| **feature_id** | `agent-tool-native-sandbox-v1` |
| **roadmap_stage** | P3.3 native AgentTool sandbox replacement；exit gate 关闭前不得扩大 AgentTool-dependent P4 |
| **architecture contract** | [`ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) v0.3.10；ADR 0012/0013 |
| **supersedes** | [`agent-tool-sandbox-v1`](agent_tool_sandbox_v1.md) v0.1.33 historical 的全部 Docker-specific runtime/provider/backend/image/lifecycle/resource 决策；保留其 provider-neutral universal executor、approved target、RPC、scope 与 workspace 契约 |
| **adapter parent** | [`erichll/pi-packages`](https://github.com/erichll/pi-packages/tree/10c8eeb8269ee478ff7383c7e6139301aa9665f9/packages/pi-sandbox) `@erichll/pi-sandbox@0.4.2` @ `10c8eeb8269ee478ff7383c7e6139301aa9665f9` |
| **isolation parent** | `@anthropic-ai/sandbox-runtime@0.0.67`（Apache-2.0；实际 OS 隔离父本） |
| **approval parent** | [`erichll/pi-packages`](https://github.com/erichll/pi-packages/tree/10c8eeb8269ee478ff7383c7e6139301aa9665f9/packages/pi-auto-review) `@erichll/pi-auto-review@0.3.2` @ 同一 frozen SHA（MIT） |
| **depends_on** | `agent-engine-extensions-v1` v0.3.0；P3 local capability loader；当前 P3.3 `AgentToolExecutor` / approved registry / JSON worker bridge |
| **path** | `docs/features/agent_tool_native_sandbox_v1.md` |
| **plan** | [`P3_3_agent_tool_native_sandbox.md`](../plans/P3_3_agent_tool_native_sandbox.md) v0.1.6 complete；[`G0 map`](../plans/P3_3_native_sandbox_G0_map.md) v0.1.0 complete |

---

## 0. 效力与变更门禁

1. 本文是 `agent-tool-native-sandbox-v1` 的冻结 feature 边界；实现必须服从 ADR 0012/0013、架构契约 v0.3.10 与 active plan。
2. ADR 0012 supersede ADR 0011/0011-A 的 Docker-specific 决策；旧 Docker feature/plan 仅作历史记录。
3. implementation plan 必须逐文件记录 `COPY / ADAPT / OMIT / NEW-HOST`，并按 Linux/macOS real gate 串行推进。
4. 本文使用：
   - **FACT**：已从当前仓库或 frozen upstream 代码确认；
   - **RESOLVED**：用户已明确决定；
   - **PROPOSED**：推荐答案，等待 grilling 确认；
   - **OPEN**：尚未决定，不得实现。

## 1. 动机与已锁定方向

### 1.1 当前问题

当前 P3.3 Docker/AIO 路径提供了强制 AgentTool 隔离，但实测存在明显成本：

- AIO-derived image 约 12.1 GB；
- cold scope acquire 约 1.386 s；
- idle scope container 约 332 MiB RSS、31 PIDs；
- warm tool call 约 35–60 ms；
- warm pool 按 scope 长时间保留容器。

目标是在不退回宿主直接执行的前提下，用 `@erichll/pi-sandbox@0.4.2` 的 native OS sandbox 机制替换 Docker 数据面。

### 1.2 已确认决定

| ID | 决定 | 状态 |
|----|------|------|
| G1 | 以 `@erichll/pi-sandbox@0.4.2` 为 adapter/security-semantics 父本 | RESOLVED |
| G2 | 在当前自实现 Python Pi Agent 中使用；不引入第二 Agent loop | RESOLVED |
| G3 | 用 Python 等价移植，不以 Node/npm 作为 production runtime | RESOLVED |
| G4 | 平台承诺 | Linux 与 macOS 都 production-capable；macOS real gate 必过；Linux real gate 可选（ADR 0013）— Linux 主机可用时运行，任何 Linux production 部署声明前必须通过 | RESOLVED |
| G5 | `pi-sandbox` 依赖的 `pi-auto-review@0.3.2` 审批能力一并做 Python 等价移植 | RESOLVED |
| G6 | 复制服从当前 Pi/App/DDD 所有权和依赖方向；能映射则尽量 COPY-semantics，冲突时才 ADAPT/OMIT | RESOLVED |
| G7 | v1 等价移植 erichll/SRT 已有能力，不额外引入 cgroup 或自制 resource monitor；保留其 timeout/process-tree cleanup | RESOLVED |
| G8 | 性能以真实对比证据验收，不为了追逐硬 SLA 改写 erichll 的 per-call broker/SRT manager 模型 | RESOLVED |
| G9 | 父本固定 `pi-sandbox@0.4.2`、SRT `0.0.67`、`pi-auto-review@0.3.2`；升级必须独立审查 source delta | RESOLVED |
| G10 | native 是唯一 production backend；验收后删除 Docker production code/dependencies/config，不保留 fallback | RESOLVED |

G3 不代表“只翻译 erichll 的 TypeScript”。erichll 的实际 OS 隔离由 `@anthropic-ai/sandbox-runtime@0.0.67` 提供；纯 Python production 路径必须同时移植本 feature 使用到的 SRT 子集，并继续调用 bubblewrap、Seatbelt、`apply-seccomp` 等原生 OS helper。

G6 所称“当前架构契约约束”专指能力归属和依赖方向，而不是继续保留将被新 ADR supersede 的 Docker-specific 实现决定。判断顺序固定为：

1. 当前 architecture contract、accepted ADR 与 frozen Pi/AgentTool 行为；
2. 当前模块所有权、依赖方向、executor/scope/RPC 生命周期；
3. erichll frozen source 的职责、输入输出和控制流；
4. 只有前三项不能同时成立时才记录 host delta，不得以“Python 风格”或个人偏好重写。

对应所有权锁定为：

- provider-neutral AgentTool execution contract 属 `packages/agent`；
- native sandbox provider/runtime、OS/process/network/filesystem IO 属 `competitive_app.adapter.out.sandbox`；
- production composition/readiness/shutdown 属 `competitive_app.wiring` / lifespan；
- `competitive_app.domain` 保持纯净，不 import sandbox、subprocess、filesystem、network 或 approval infrastructure；
- `packages/ai` 不承载 sandbox policy；`pi-auto-review` 的 model call 复用它的公开模型能力，但 approval policy 留在 App/capability 边界。

## 2. 当前仓库事实与保留边界

### 2.1 保留现有 Pi executor seam

当前仓库已经具有 provider-neutral：

```text
packages/agent/.../tool_execution.py
  AgentToolExecutor
  DirectToolExecutor
  ToolExecutionTarget
```

该 seam 保持不知道 bubblewrap、Seatbelt、SRT、Docker 或 App 配置。native sandbox 仍由 `competitive_app.adapter.out.sandbox` 实现并在 App wiring 注入。

### 2.2 保留的 P3.3 行为

以下行为不因替换 Docker 而删除：

1. `competitive_app` production 的每次 `AgentTool.execute()` 都经过同一 executor，禁止按工具名、package、main/sub-agent 绕过。
2. `DirectToolExecutor` 仅用于 standalone Pi parity 和显式测试注入，不是 production fallback。
3. approved registry 是 tool name 到 `module + qualname` 的唯一可信绑定，模型不能选择 target。
4. worker 只执行 module-level four-argument async callable。
5. `agent-tool-rpc.v1` 继续承载 request、ordered update、single terminal result/error。
6. parent session 继续拥有稳定 scope id；ephemeral sub-agent 继承 parent scope/workspace。
7. workspace 继续位于 `data/sandboxes/<scope-id>`，resume 复用，显式 task delete 才删除。
8. sandbox 不可用或初始化失败必须 fail closed。
9. native provider 是唯一 production provider；不存在 Docker/native provider switch、Docker fallback 或并行保留的 production backend。

### 2.3 不直接照抄 erichll 的 Pi extension 入口

erichll `index.ts` 通过覆盖 Bash tool、`user_bash` hook 和自带 subagent tool 接入官方 Pi coding agent。当前项目已经在 low-level `AgentToolExecutor` 收口全部 Python AgentTool，因此照抄该入口会：

- 只覆盖 Bash，降低现有 universal coverage；
- 形成第二套工具注册路径；
- 重复当前 ephemeral sub-agent orchestration。

本 feature 移植 erichll 的 sandbox engine，不移植其 extension registration 产品面。

## 3. 目标拓扑

```text
FastAPI / Pi Agent / Session（宿主 Python 控制面）
  -> AgentToolExecutor
  -> SandboxToolExecutor
  -> NativeSandboxProvider
  -> NativeSandboxRuntime
  -> 每次调用一个独立 Python broker process
       -> Python SRT subset
       -> Linux: bubblewrap + apply-seccomp
       -> macOS: Seatbelt sandbox-exec
       -> Python AgentTool worker
  <- agent-tool-rpc.v1 JSONL frames
```

### 3.1 进程职责

| 进程 | 职责 | 禁止 |
|------|------|------|
| Host App | Agent loop、LLM、validation、extension lifecycle、session、registry、approval | 直接执行 production AgentTool |
| Python broker | 建立一次调用的 policy、proxy、OS sandbox、取消和清理 | Agent loop、LLM、workflow、动态 target 选择 |
| Python worker | 校验 manifest，import approved callable，执行一次 request，输出 JSONL frames | 读取 Host Python object、pickle/eval/source injection、启动第二 Agent |

每个并行 tool call 使用独立 broker/SRT manager，与 erichll 的 per-command isolation 一致；不复用一个可能已被工具污染的 worker。

### 3.2 平台支持

Linux 和 macOS 都属于 production 支持范围，不把 macOS 降级为仅开发或 CI 平台：

- Linux 等价移植 erichll/SRT 的 bubblewrap mount/network/PID namespace 与 seccomp 路径；
- macOS 等价移植 erichll/SRT 的 Seatbelt profile 与 sandbox-exec 路径；
- **macOS（arm64）real enforcement 是正式必过 gate**；**Linux real enforcement 是可选项**（ADR 0013）：Linux amd64 主机/CI 可用时运行同一 S1–S9 套件，结果作为 Linux production 部署前提；不阻塞 P3.3 closeout；
- 两个平台的离线 parity、fail-closed 与 no-host-fallback 要求一致；平台固有差异必须记录，但不能成为 macOS 绕过或宿主 fallback 的理由。

## 4. Upstream 移植边界

### 4.1 `@erichll/pi-sandbox@0.4.2`

| upstream | Python target | 分类 | 约束 |
|----------|---------------|------|------|
| `src/runner.ts` | `native/runner.py` | ADAPT | `fork` 改为 `asyncio` subprocess；保持 detached process group、timeout、abort、network IPC、finally kill |
| `src/srt-broker.mjs` | `native/broker.py` | ADAPT | 单 init message、SRT initialize/wrap/reset、target stdio pipe、异常 exit 1 |
| `src/policy.ts` | `native/policy.py` | ADAPT | 保持 deny/allow 语义；Node install roots 改为可信 Python runtime/tool bundle roots |
| `src/config.ts` | `native/config.py` | ADAPT | 严格 schema、unknown key 拒绝、绝对路径校验、malformed config 阻止 startup |
| `src/network-policy.mjs` | `native/network_policy.py` | COPY-semantics | hostname 规范化、DNS 全地址校验、私网/loopback/link-local/multicast 拒绝 |
| `src/approval.ts` | `native/approval.py` | ADAPT | Python `ApprovalBroker` Protocol；broker 缺失/异常/无有效一次性 grant 均 deny |
| `src/traps.ts` | `native/traps.py` | COPY-semantics | filesystem/network trap 类型与稳定格式 |
| `src/index.ts` | — | OMIT | 由当前 `AgentToolExecutor` 与 App wiring 取代 |
| `src/subagent.ts` | — | OMIT | 当前 ephemeral sub-agent 已继承 parent executor/scope |
| `src/host-ipc.ts` | — | OMIT | 宿主重试违反 production no-fallback；即使 erichll 默认关闭也不移植开关 |

### 4.2 `@anthropic-ai/sandbox-runtime@0.0.67`

Python 端只移植 erichll 实际调用所需子集：

```text
native/srt/
  manager.py              initialize / wrap / cleanup / reset
  policy.py               strict config normalization
  linux.py                bubblewrap argv、namespace、mount/network policy
  macos.py                Seatbelt profile/argv
  seccomp.py              filter generation + apply-seccomp helper invocation
  proxy.py                HTTP/SOCKS/domain approval transport
  process.py              helper discovery、stdio、process cleanup
```

不因“完整复刻 SRT”扩大到当前 feature 未使用的 Windows、credential rewriting、AWS signing 或通用 CLI 产品面。直接复制或实质改编必须保留 Apache-2.0 notice、精确版本/path 和 host delta。

### 4.3 `@erichll/pi-auto-review@0.3.2`

`pi-sandbox` 的 per-connection network approval 依赖 `pi-auto-review`，因此以下核心不是可选增强：

| upstream | Python target responsibility | 分类 |
|----------|------------------------------|------|
| `src/broker/types.ts` | `packages/agent` generic boundary contract + capability concrete types | COPY-semantics |
| `src/broker/broker.ts` | hard deny -> reviewer -> exact grant 决策顺序 | ADAPT |
| `src/broker/grants.ts` | stable request hash、TTL、single-use grant | COPY-semantics |
| `src/broker/circuit-breaker.ts` | 连续/滚动拒绝熔断 | COPY-semantics |
| `src/broker/overrides.ts` | exact retry override store | COPY-semantics；仅在 Host 有对应用户授权入口时启用 |
| `src/broker/service.ts` | `packages/agent` extension runtime service publication/lookup + explicit App wiring DI | ADAPT，不使用 JS global Symbol |
| `src/integrations/sandbox.ts` | App SRT trap -> generic boundary request adapter | COPY-semantics |
| `src/policy.ts` | `capability_packages/pi_auto_review` strict model decision、hard deny、bounded/redacted evidence | ADAPT 到 `earendil_works.pi_ai` message/result 形状 |
| `src/index.ts` reviewer core | local capability trusted config、reviewer model call、failure mode、grant issuance | ADAPT 到当前唯一 Python model registry/session context |
| `src/ui-auto-confirm.ts` / `src/user-feedback.ts` | TUI 自动确认、toast/footer | OMIT until mapped；当前 App 没有 coding TUI，不得为字面复刻引入第二 UI/runtime |

约束：

- model review 必须复用 `earendil_works.pi_ai`，禁止引入第二 LLM framework；
- generic broker/service contract 属 `packages/agent`，不含 sandbox/App policy；
- reviewer/policy/grant/circuit-breaker 属 `capability_packages/pi_auto_review`，通过当前 local loader/extension runtime 启用；
- App sandbox adapter 通过 wiring 显式注入的 broker contract 调用审批，不从 global mutable singleton 猜测依赖；
- hard deny、exact hash、one-shot/expiring grant、failureMode deny、circuit breaker 与 evidence redaction 必须保持；
- UI 不存在时 reviewer defer 必须 deny，不能自动 allow；
- project-local config 只能收紧 trusted config，不能扩大权限。

## 5. 目标代码所有权

```text
packages/agent/src/earendil_works/pi_agent/
  tool_execution.py                         KEEP
  boundary_approval.py                      NEW-HOST generic broker/service seam only

capability_packages/pi_auto_review/
  extensions/                               NEW PORT reviewer/policy/grants/breaker
  package.json                              local capability manifest

competitive_app/src/competitive_app/adapter/out/sandbox/
  approved_registry.py                      KEEP
  protocol.py                               KEEP
  worker.py                                 ADAPT manifest path/runtime packaging
  sandbox_tool_executor.py                  ADAPT signal/abort propagation
  lifecycle.py                              ADAPT native readiness/cleanup
  native/
    config.py                               NEW PORT
    policy.py                               NEW PORT
    traps.py                                NEW PORT
    approval.py                             NEW PORT sandbox trap/broker adapter only
    network_policy.py                       NEW PORT
    runner.py                               NEW PORT
    broker.py                               NEW PORT
    native_runtime.py                       NEW-HOST adapter
    native_sandbox_provider.py              NEW-HOST adapter
    srt/                                    NEW PORT of required SRT subset

competitive_app/src/competitive_app/wiring.py
                                            ADAPT Docker composition -> native
```

`competitive_app.domain`、`packages/ai` 和 Pi Agent loop 不得 import native sandbox 实现。

## 6. Filesystem policy

### 6.1 默认 policy

一次 tool call 的 `cwd` 是 scope workspace，不是仓库根目录。默认：

- workspace 可读写；
- Python runtime、已安装 capability tool bundle、SRT helper 精确只读；
- Host home 默认 deny read；
- App source、`.git`、`.env`、session JSONL、SQLite、Docker socket 和其他 scope workspace 不可见；
- trusted sandbox config、extension/package files、Git hooks 不可写；
- erichll 的 workspace secret deny-write 规则保持，包括 `.env*`、`secrets/`、`.secrets/`、private key/certificate 后缀及 bounded scan；
- Linux literal-path 与 macOS glob 能力差异必须在测试和残余风险中明确记录。

### 6.2 Trusted tool bundle

native worker 不从可写 workspace 加载 Python tool code。approved capability、worker、manifest 及依赖必须来自 startup 已验证的只读安装目录；manifest identity 必须与 Host registry 一致。

## 7. Network 与 approval

1. 默认 deny network；未匹配连接提交精确 `hostname:port` approval。
2. hostname 在 broker 内完成规范化和 DNS 校验；任一解析结果为非公网地址即拒绝。
3. approval broker 不可用、异常、超时、grant 不匹配或已消费时拒绝。
4. filesystem deny 不动态提升为 allow；与 erichll 保持 static fail-closed。
5. production 无交互 UI 时不得隐式批准。

G5 已锁定为 Python 等价移植 `pi-auto-review@0.3.2` 的 sandbox 所需核心。production 网络请求必须经过该 broker；不存在 UI 时，只有 deterministic/model reviewer 返回且成功消费 exact one-shot grant 的请求可以放行，defer/异常/超时均 deny。

### 7.1 Environment boundary

erichll runner 默认继承 caller environment，但当前 P3.3 已锁定只向 tool worker 提供七项 search provider 配置。移植必须服从当前更窄边界：

- 不复制完整 Host environment；
- 继续使用当前 `_ALLOWED_ENVIRONMENT` allowlist；
- 不传 LLM secret、session/App 配置、Host proxy/socket 或其他无关变量；
- approval reviewer 所需 model credential 留在 Host，不进入 sandbox worker。

## 8. 执行、并行、取消与清理

1. 每次调用独立 broker、policy、proxy 和 target process tree。
2. broker 必须建立独立 process group/session；abort 和 timeout 杀死完整 process tree。
3. `SandboxToolExecutor` 必须传播 Pi `signal`，不得像当前 Docker scope-abort 路径一样丢弃。
4. 同 scope parallel tools 使用独立 broker 并共享同一 workspace；不得用全局 runtime lock 串行化。
5. broker/SRT init、target spawn、protocol、approval、timeout 或 cleanup 失败均返回脱敏 sandbox error，不在 Host 重试执行 tool。
6. scope abort 必须终止该 scope 所有 active brokers；正常单调用完成只清理自身 broker。
7. scope idle 时不得保留 worker、broker 或 per-scope proxy 进程。

### 8.1 Resource behavior

v1 以 erichll/SRT 的能力等价为上限，不在直接移植中加入 cgroup 或自制 macOS resource monitor：

- 保留 erichll runner 的 wall timeout、abort 和 detached process-group tree kill；
- 保留当前 JSON RPC 的 request/frame/update/result size limit，防止控制面被无界协议输出拖垮；
- SRT/broker/target cleanup 失败必须 fail closed 并执行 best-effort tree kill；
- 不承诺 Docker 原有的 CPU、memory、PID、filesystem-size hard quota。

这是 native 替换 Docker 后的显式残余风险，不得在文档或验收中伪装为仍有容器级 quota。后续若需要 quota，必须独立 feature/ADR，不混入本次“应抄尽抄”的移植。

## 9. 配置与 startup readiness

候选 production 配置只允许 trusted App composition 提供，Agent、workspace 和 project-local extension 不得修改：

```text
sandbox.root
sandbox.tool_bundle_root
sandbox.manifest_path
sandbox.additional_allow_read
sandbox.network_policy / approval broker binding
```

禁止：

- `enabled=false`；
- provider runtime fallback；
- Host IPC；
- unsupported platform 自动 direct execute；
- malformed config 使用宽松默认值继续启动。
- Docker image、daemon、SDK、provider switch 或 Docker fallback 配置。

startup readiness 必须真实验证：helper 可执行、unprivileged namespace/Seatbelt 可用、home read denied、workspace write allowed、network default denied、manifest/registry 一致、broker cleanup 成功。

## 10. 验收门禁

### 10.1 Contract/offline

- universal AgentTool coverage 不回退；
- main、resume、dynamic tools、extension tools、ephemeral sub-agent 使用同一 executor；
- registry/manifest target mismatch fail closed；
- malformed config、unknown key、unsupported platform fail closed；
- no Node/npm production runtime；
- license/source/host-delta 完整。

### 10.2 Real OS enforcement

- **macOS（arm64）必过**：Seatbelt profile 真实生效，workspace read/write allow；scope escape deny；
- home、`.env`、session、DB、App config、tool bundle write deny；
- symlink/path traversal 不扩大可见边界；
- network default deny；批准只作用于精确 endpoint；private/metadata/DNS mixed result deny；
- timeout/abort 杀死完整 process tree，无 orphan；
- broker/SRT/proxy crash 不触发 Host execution；
- 同 scope 和跨 scope 并行均真实执行且隔离正确。
- **Linux（amd64）可选**（ADR 0013）：同一 S1–S9 套件在 Linux 主机运行时 green；Linux production 部署前必须执行。

### 10.3 Performance/resource evidence

必须与 ADR 0012 记录的 Docker 基线对比（优先同一台 arm64 macOS host；Linux amd64 host 可用时补充对比）：

- cold first tool call；
- steady tool call；
- idle per-scope RSS/PIDs；
- 10 个并行调用的 latency/RSS/PIDs；
- abort 后残留进程；
- 安装/运行时磁盘占用。

G8 不锁定人为数值 SLA。验收必须提交同机 cold/steady/parallel/idle/disk 对比数据并解释任何退化，但不得为了让数字好看而偏离 erichll 的 per-call independent broker/SRT manager 安全模型。Docker 只作为迁移前基线，不是保留的 backend。

## 11. 已知残余风险

1. erichll/SRT 没有 Docker 当前提供的 CPU、memory、PID 和 filesystem size quota。
2. Linux 与 macOS 使用不同的内核隔离原语；Seatbelt 没有 Linux PID/user/mount namespace，但两者都必须满足本 feature 锁定的对外行为与 fail-closed 契约。**ADR 0013 后：Linux real enforcement 未执行前，Linux production 真实行为（bubblewrap/seccomp 生效）为未验证状态**；macOS 真实行为已由必过 gate 验证。
3. SRT 是 research preview；Python port 需要独立追踪 upstream security fixes。
4. Linux filesystem deny 对不存在的深层动态 secret path 受 literal mount/path 能力限制。
5. bubblewrap/Seatbelt/seccomp 是宿主内核边界，不等同于 VM/microVM kernel isolation。
6. workspace 在同一 scope 并行调用间共享，恶意调用可以影响该 scope 的其他调用。

## 12. Grilling 决策队列

| ID | 问题 | 推荐答案 | 状态 |
|----|------|----------|------|
| G1 | sandbox adapter 父本 | erichll `0.4.2` frozen SHA | RESOLVED |
| G2 | 接入哪套 Agent | 当前 Python Pi Agent，保留唯一 Agent loop | RESOLVED |
| G3 | 是否允许 Node/npm production runtime | 不允许；Python 移植 erichll + required SRT subset | RESOLVED |
| G4 | production 平台承诺 | Linux 与 macOS 都 production-capable；macOS real gate 必过；Linux real gate 可选（ADR 0013），Linux production 部署声明前必须通过 | RESOLVED |
| G5 | 无 UI server 的 network approval | Python 等价移植 `pi-auto-review@0.3.2` sandbox 核心；复用 Pi model registry；无有效 exact grant 即 deny | RESOLVED |
| G6 | 如何理解“在当前架构契约约束下抄” | 保持 Pi/App/DDD 能力归属和依赖方向；不等于保留 Docker-specific 决策；沿用现有七项 provider env allowlist | RESOLVED |
| G7 | resource quota 缺失是否阻止替换 Docker | 不阻止；v1 等价移植 erichll/SRT，保留 timeout/process-tree cleanup，不新增 cgroup/monitor；quota 缺失列为残余风险 | RESOLVED |
| G8 | 是否锁定性能 SLA | 不锁人为 SLA；强制同机 Docker baseline 对比和 idle zero-process 证据，不为性能改写 frozen erichll 进程模型 | RESOLVED |
| G9 | Python SRT port 更新策略 | frozen 三版本起步；后续升级逐版本审查 source/security/behavior delta，不追 floating latest | RESOLVED |
| G10 | Docker 代码处置 | native gate 通过后删除 Docker production provider/backend/runtime/image/SDK/config；不保留 runtime 或 fallback；历史 ADR/feature 仅作记录 | RESOLVED |

## 13. Freeze / implementation gate

G1–G10、ADR 0012/0013、architecture contract v0.3.10 与 Roadmap/plan 同步已完成；G0 source/test/removal evidence 已冻结。实现只能按 plan v0.1.4 + G0 map 推进；macOS real gate（V3）、offline parity（V1）、Docker production removal 与文档/license 审计（V4）完成前不得关闭 P3.3；Linux real gate（V2）为可选项，不阻塞关闭。

## 14. 修订记录

| Version | Date | Change |
|---------|------|--------|
| `0.2.2` | 2026-08-03 | **ADR 0013**：Linux real-enforcement gate 改为可选项（V2 不阻塞 closeout，Linux production 部署前必过）；macOS real gate 保持正式必过；§3.2/G4/§10.2/§10.3/§11/§13 措辞修订；contract v0.3.10 |
| `0.2.1` | 2026-08-02 | No behavior change：G0 evidence complete；link frozen source/integrity/license/seccomp/removal/CodeGraph/test map；plan v0.1.1 active |

