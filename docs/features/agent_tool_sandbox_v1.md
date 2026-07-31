# Feature 边界契约：agent-tool-sandbox-v1

| 字段 | 值 |
|------|-----|
| **feature_contract_version** | `0.1.32` |
| **status** | **frozen — G1–G30 resolved；ADR 0011 + 0011-A accepted；implementation plan v0.1.2 active** |
| **created** | 2026-07-31 |
| **updated** | 2026-08-01 |
| **feature_id** | `agent-tool-sandbox-v1` |
| **roadmap_stage** | **P3.3 AgentTool sandbox**：P3.2 后、继续扩大依赖 AgentTool 的 P4 业务面前关闭 exit gate |
| **architecture_contract** | [`ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.8**；ADR 0011 + 0011-A |
| **depends_on** | [`agent-engine-extensions-v1`](agent_engine_extensions_v1.md) v0.3.0；P3 local capability loader；P4 `competitive_app` wiring / lifecycle |
| **代码参考父本** | [`HezaoHezao/poirot`](https://github.com/HezaoHezao/poirot/tree/86bf279ad90c180f0ba696755620dd7d6661465e) frozen SHA [`86bf279`](https://github.com/HezaoHezao/poirot/commit/86bf279ad90c180f0ba696755620dd7d6661465e) |
| **Pi 对照（调查快照）** | [`earendil-works/pi`](https://github.com/earendil-works/pi/tree/471c3390fe015de9b7308fce0ada5bc7c3bb7d3c) `main` @ `471c3390fe015de9b7308fce0ada5bc7c3bb7d3c`；仅为 2026-07-31 forensics，实施仍须重新对照当时 `main` |
| **Pi 实施前复核** | `main` @ `784653468c42387f607d41ed5ca533100e7eb2fe`（2026-07-31 plan preflight）；`executePreparedToolCall` 仍直接调用 tool，实施 PR 仍须复核当时 `main` |
| **许可证** | Poirot = MIT；`agent-sandbox` SDK = Apache-2.0；直接复制/实质改编文件必须保留 immutable source、copyright、license notice 与 host delta |
| **path** | `docs/features/agent_tool_sandbox_v1.md` |
| **plan** | [`P3_3_agent_tool_sandbox.md`](../plans/P3_3_agent_tool_sandbox.md) **v0.1.2 active**；实现只能按 plan 串行推进 |

---

## 0. 效力、状态与阅读约定

1. 本文是 `agent-tool-sandbox-v1` 的**冻结需求边界契约**；MUST/禁止项约束后续 implementation plan 与实现。
2. 本文使用三类标记：
   - **FACT**：已从当前仓库、Pi upstream 或 Poirot frozen SHA 的代码确认；
   - **RESOLVED / 锁定**：G1–G30 已确认边界；
   - **COPY / ADAPT / OMIT / NEW-HOST**：Poirot transplant 分类。
3. 架构效力来自 accepted ADR 0011 + 0011-A + [`ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) v0.3.8；Roadmap P3.3 负责实施顺序与 exit gate。
4. implementation 只能按 [`P3_3_agent_tool_sandbox.md`](../plans/P3_3_agent_tool_sandbox.md) 的阶段与门禁推进；仍禁止：
   - 修改 `packages/agent` 的 tool execution 语义；
   - 把 Poirot sandbox 代码直接落仓；
   - 新增 Docker/SDK 生产依赖；
   - 用“Local sandbox”或路径检查冒充进程隔离；
   - 为赶进度保留 sandbox 失败后宿主执行的 fallback。
5. implementation plan 已逐文件标明 `COPY / ADAPT / OMIT / NEW-HOST`；模块职责、输入输出与生命周期可映射时必须优先 `COPY`，不得无理由改写。
6. 范围硬上限：Poirot 没有且用户未明确要求、现有架构/生产语义/已锁定决定也不强制的能力，一律 `OMIT`；“更安全”“以后可能需要”或通用最佳实践本身不能扩大本 feature。

---

## 1. 动机与目标

### 1.1 当前问题

当前 `AgentTool` 在 FastAPI/Agent 所在 Python 进程内直接执行。工具参数来自模型输出；搜索工具会访问网络，未来本地 capability 还可能读写文件、执行命令或处理不可信内容。现状没有操作系统级边界来限制：

- 工具读取宿主文件和进程环境；
- 工具影响其他 task/session 的数据；
- 工具耗尽 CPU、内存、PID、磁盘或运行时间；
- 工具代码/依赖缺陷拖垮 Agent/HTTP 控制面；
- prompt/tool 参数诱导产生非预期副作用；
- 单个 capability 获得与其职责无关的 secret。

### 1.2 核心目标

1. `competitive_app` 生产运行路径中的每一次 `AgentTool.execute()` 都在隔离容器内执行。
2. Pi Agent、LLM provider、参数校验、extension lifecycle、session/JSONL 和 App Process Manager 继续在唯一宿主控制面运行。
3. sandbox 不可用、tool target 不可远程加载、协议不兼容或结果不可序列化时 **fail closed**；禁止静默回退宿主执行。
4. 保持 Pi 工具语义：
   - schema validation / `prepareArguments`；
   - `beforeToolCall` / `afterToolCall`；
   - extension `tool_call` / `tool_result`；
   - sequential / parallel；
   - abort / timeout；
   - `on_update` partial result；
   - `AgentToolResult` / error tool result / JSONL 顺序。
5. 以 Poirot frozen SHA 为 transplant-first 代码父本，优先复用其 sandbox facade、contracts、provider lifecycle、Docker backend、path/guard/audit 与测试；只为“任意 AgentTool 远程执行”和本仓架构边界新增必要 glue。
6. 保持唯一 Agent 内核为 `earendil_works.pi_agent`；sandbox 内不得启动第二 Agent loop、第二 LLM framework 或复制 P4 workflow。

### 1.3 锁定非目标

| 不做 | 当前推荐理由 | 状态 |
|------|--------------|------|
| 把整个 FastAPI / Agent / LLM 进程放入每个 sandbox | 会复制控制面和 session/extension runtime，违反唯一 Agent 内核与单控制面目标 | LOCKED |
| 远程安装 capability package | 维持 D22 / ADR 0006 本地 only | LOCKED |
| 搬 Poirot LangChain/LangGraph middleware | 当前仓库禁止第二 LLM/Agent framework | LOCKED |
| v1 提供通用 coding shell/file 工具 | 本目标是隔离现有 AgentTool，不扩产品工具面 | LOCKED |
| v1 实现 K8s/E2B/云 sandbox provider | 只交付 Docker production path；远端 provider 另 feature | LOCKED |
| sandbox 替代 capability/tool 权限 policy | sandbox 是最后隔离边界，不替代工具白名单、参数校验或 provider policy | LOCKED |

---

## 2. 已确认的代码事实（FACT）

### 2.1 当前 Pi 工具执行路径

当前唯一真实执行点位于 [`agent_loop.py`](../../packages/agent/src/earendil_works/pi_agent/agent_loop.py#L705)：

```python
result = await prepared["tool"].execute(
    prepared["toolCall"]["id"],
    prepared["args"],
    signal,
    on_update,
)
```

其前后顺序已经固定为：

```text
tool_execution_start
  → prepareArguments
  → JSON Schema validation
  → beforeToolCall / extension tool_call
  → AgentTool.execute
  → afterToolCall / extension tool_result
  → tool_execution_end
  → ToolResultMessage
  → Session JSONL
```

截至调查时的 Pi upstream `main`，[`executePreparedToolCall`](https://github.com/earendil-works/pi/blob/471c3390fe015de9b7308fce0ada5bc7c3bb7d3c/packages/agent/src/agent-loop.ts#L666-L700) 仍直接调用 `prepared.tool.execute(...)`，没有 upstream `ToolExecutor` seam。因此任何全局 executor 都是必须由 ADR 明示的 Python host delta，不能声称为上游同构代码。

### 2.2 不能只包装 startup tools

| FACT | 代码证据 | 影响 |
|------|----------|------|
| `AgentTool` 只有 callable `execute`，无远程 target metadata | [`types.py`](../../packages/agent/src/earendil_works/pi_agent/types.py#L119-L137) | worker 无法从 tool name 安全定位 callable |
| extension wrapper 把原 execute 捕获进局部闭包 | [`extensions/wrapper.py`](../../packages/agent/src/earendil_works/pi_agent/extensions/wrapper.py#L16-L34) | 运行时看到的是 `<locals>.wrapped`，原 module/qualname 丢失 |
| workflow 会动态替换 `agent.state.tools` | [`research_runner.py`](../../competitive_app/src/competitive_app/application/workflow/research_runner.py#L174) | startup 一次包装会被后续赋值绕过 |
| ephemeral sub-agent 直接接收工具列表 | [`wiring.py`](../../competitive_app/src/competitive_app/wiring.py#L185-L227) | 只改主 Harness 不能覆盖 sub-agent |
| `beforeToolCall` 只能 block，不能提供替代执行结果 | [`agent_loop.py`](../../packages/agent/src/earendil_works/pi_agent/agent_loop.py#L638-L702) | 不能用已有 hook 诚实实现 remote execute |

结论：完整覆盖必须收口在 low-level `AgentTool.execute` 调用处，或提供与该调用等价且不可绕过的 executor transport；不能靠 App 启动时逐个 monkey-wrap。

### 2.3 当前生产工具具备可迁移形状

当前 capability 中六个生产工具的 execute 均为模块顶层 async 函数：

| 工具 | callable |
|------|----------|
| `echo` | `capability_packages.echo_example.extensions.echo_tools:_echo_execute` |
| `tavily_search` | `capability_packages.search_tavily.extensions.tavily_tools:_tavily_search_execute` |
| `tavily_fetch` | `capability_packages.search_tavily.extensions.tavily_tools:_tavily_fetch_execute` |
| `anysearch_search` | `capability_packages.search_anysearch.extensions.anysearch_tools:_anysearch_search_execute` |
| `anysearch_fetch` | `capability_packages.search_anysearch.extensions.anysearch_tools:_anysearch_fetch_execute` |
| `grok_search` | `capability_packages.search_grok.extensions.grok_tools:_grok_search_execute` |

这些函数的当前参数和结果都是 JSON-compatible 形状，且生产代码没有调用 `on_update`。这降低首批迁移风险，但不能删除 AgentTool contract 已存在的 partial update 语义。

### 2.4 Poirot sandbox 的真实边界

Poirot frozen SHA 的核心是：

```text
Sandbox = Runtime + PathTranslator + SecurityGuard
              │
              └─ validate → translate → execute → mask

SandboxProvider
  ├─ deterministic thread sandbox id
  ├─ in-process cache
  ├─ warm pool / replicas
  ├─ cross-process discover/create lock
  ├─ readiness
  ├─ idle cleanup
  └─ shutdown/orphan reconciliation
```

关键代码：

- [`sandbox.py`](https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/sandbox/sandbox.py)；
- [`docker_sandbox_provider.py`](https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/sandbox/docker/docker_sandbox_provider.py)；
- [`docker_runtime.py`](https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/sandbox/runtimes/docker_runtime.py)；
- [`local_container_backend.py`](https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/sandbox/docker/local_container_backend.py)。

但 Poirot 的 integration 只注册并路由六个专用工具：`bash/read_file/write_file/list_dir/str_replace/present_files`。[`SandboxMiddleware`](https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/middlewares/sandbox_middleware.py#L79-L125) 对其他工具直接 passthrough；其 [`test_web_search_no_acquire`](https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/tests/v1/unit/sandbox/test_middleware.py#L48-L57) 明确验证搜索不进 sandbox。

因此：**Poirot 是 sandbox-native tool facade，不是任意 Python AgentTool remote executor。**

### 2.5 Poirot 不能原样继承的安全/兼容事实

1. `LocalRuntime` 使用 `subprocess.run(shell=True)` 和宿主文件 API；它是开发期路径映射，不是进程隔离。
2. Docker 启动参数包含 `--security-opt seccomp=unconfined`，且没有：
   - `--cap-drop=ALL`；
   - `--security-opt=no-new-privileges`；
   - read-only rootfs；
   - CPU / memory / PID / file-size 限额；
   - 网络出站限制；
   - non-root user；
   - Docker socket 禁挂的显式门禁。
3. 默认镜像为浮动 `all-in-one-sandbox:latest`。
4. Poirot 声明 `agent-sandbox>=0.0.19`，但其 `DockerRuntime` 使用 `no_change_timeout`；0.0.19 SDK 没有该参数，调查时 0.0.30 才具备相应 API。
5. Poirot `DockerRuntime.exec_command()` 用一个 `threading.Lock` 串行所有命令；直接复用会破坏当前 AgentTool parallel 语义。
6. Poirot sandbox id 只取 SHA-256 前 8 个 hex 字符；多租户隔离使用 32-bit key 存在不可接受的碰撞风险。

---

## 3. 术语与锁定边界

### 3.1 AgentTool 调用（G3 locked）

本文中的“AgentTool 调用”锁定定义为：

```text
经过 schema validation 和 beforeToolCall 后，
产生 AgentToolResult 或异常的 execute 阶段。
```

它不包括且必须留在可信宿主控制面：

- capability package 的 discovery、module import、module-level code 和 `register(api)`；
- `prepareArguments`；
- extension registration、wrapper construction 和 event handlers；
- LLM provider request；
- App workflow / DB / SOCM；
- session JSONL persistence。

**G3 信任边界：** capability package 在 discovery/import/register/prepare/extension 阶段仍是宿主可信代码。本 feature 隔离的是通过校验后的 `execute()` 调用及其执行期副作用，不承诺阻止恶意或供应链污染的 package 在宿主加载/注册阶段执行代码。

### 3.2 控制面与工具执行面

| 面 | 职责 | 运行位置 |
|----|----------|--------------|
| 控制面 | FastAPI、Pi Agent loop、LLM、validation、extensions、Session、Process Manager | 宿主唯一 Python 进程 |
| 工具执行面 | 导入一个已批准 AgentTool target 并执行其 `execute()` | Docker sandbox |
| sandbox lifecycle | create/discover/acquire/release/idle/shutdown | `competitive_app` out adapter + wiring |
| worker protocol | request/update/result/error frame | container image 内的最小 Python worker |

### 3.3 “全部进入 sandbox”的 fail-closed 含义

生产模式下，下列任一情况发生时不得调用宿主 `tool.execute()`：

- executor 未注入；
- scope id 缺失；
- tool 无合法 remote target；
- target 不在启动时批准的 registry；
- sandbox/provider/image 不可用；
- host/worker protocol version 不一致；
- request/result 超大小或不可 JSON 序列化；
- worker 超时、被 abort、崩溃或容器消失。

上述 execute 期失败按 G29 锁定为脱敏、可观测的 error tool result，不升级为 sandbox 专属 task failure，且始终禁止 host fallback。

---

## 4. 锁定威胁模型（G17–G21 resolved）

### 4.1 需要防护的输入/主体

1. 模型生成的恶意或错误 tool arguments；
2. 被 prompt injection 污染的网页/provider 内容；
3. 已通过可信加载和注册的 capability，其 `execute()` 路径存在缺陷或被不可信输入诱导产生越权副作用；
4. 失控、死循环、fork bomb、内存/磁盘耗尽的工具；
5. 一个 task/session 试图读取另一个 scope 的 workspace；
6. 工具读取未注入 sandbox 的宿主 secret；同 scope 内七项 search provider 配置按 G21 明确共享，不提供 per-tool secret isolation；
7. 工具试图访问 Docker daemon、宿主 socket 或宿主文件系统。

### 4.2 建议保护资产

- FastAPI / Pi Agent 控制面可用性；
- 宿主文件系统（sandbox workspace 之外）；
- 其他 task/session/tenant 的 sandbox 数据；
- `.env`、模型密钥、数据库、session JSONL 和 Docker socket；
- tool result / logs 中的 secret；
- session transcript 的完整顺序和可恢复性。

### 4.3 G3 锁定的范围外风险

本 feature 不隔离 capability package 在宿主执行的 module import、module-level code、`register(api)`、`prepareArguments` 或 extension handler。恶意/供应链污染 package 的加载期防护必须由来源 pin、审核、签名或另行冻结的 capability supply-chain feature 处理；不得把 AgentTool execute sandbox 宣传成该风险的防线。

### 4.4 G20 锁定的网络非目标与残余风险

v1 明确不承诺：

- 禁止或限制 container 公网 egress；
- provider 域名级 allowlist、egress proxy/firewall 或 URL/DNS policy；
- 阻断 container 到宿主/LAN、private/link-local/metadata 或 sibling container address 的网络可达性；
- 对内核零日逃逸的强隔离保证；
- confidential computing；
- 跨物理机租户隔离；
- 恶意 root container 的形式化安全证明。

理由不是宣称这些风险不存在，而是 Poirot frozen sandbox 没有对应实现/测试，用户也未要求新增网络安全子系统；G3 已锁定 capability package/execute target 为受信代码，当前工具只使用受信配置中的 provider endpoint。Docker 默认出站、配置错误或受信 tool 缺陷仍可能访问非预期网络目标，属于 v1 接受并必须如实记录的残余风险。

---

## 5. 目标拓扑（locked）

```text
Clients → FastAPI / competitive_app
                    │
                    ▼
             Pi Agent loop (host)
       validate → beforeToolCall / tool_call
                    │
                    ▼
       AgentToolExecutor (provider-neutral seam)
                    │ scope + approved target + JSON args
                    ▼
       DockerSandboxProvider
                    │ one shell/process session per tool call
                    ▼
       pinned tool-worker container
       importlib(module, qualname) → await execute(...)
                    │ JSONL update/result/error frames
                    ▼
       afterToolCall / tool_result → ToolResultMessage
                    │
                    ▼
             Session JSONL (host SoT)
```

### 5.1 `packages/agent` 最小 seam（NEW-HOST）

锁定公共形状：

```python
class AgentToolExecutor(Protocol):
    async def execute(
        self,
        *,
        scope_id: str,
        tool: AgentTool,
        tool_call_id: str,
        params: Any,
        signal: Any | None,
        on_update: AgentToolUpdateCallback,
    ) -> AgentToolResult: ...
```

low-level loop 的语义变化限制为：

```python
executor = config.toolExecutor or DIRECT_TOOL_EXECUTOR
result = await executor.execute(
    scope_id=config.toolExecutionScopeId,
    tool=prepared["tool"],
    tool_call_id=prepared["toolCall"]["id"],
    params=prepared["args"],
    signal=signal,
    on_update=on_update,
)
```

限制：

1. `AgentToolExecutor` 是 transport seam，不得拥有 LLM、Agent state、workflow 或业务 policy。
2. `DirectToolExecutor` 必须与当前/上游 `tool.execute(...)` 行为 parity，作为 `pi_agent` 独立 library 的默认 executor；它不得成为 `competitive_app` production 的隐式或显式 fallback。
3. executor 调用仍处在既有 before/after、events 和 error finalization 之间，不改变事件次序。
4. executor 不得重新做一套 tool schema validation 或 extension dispatch。

### 5.2 G3 锁定：宿主保留的行为

**RESOLVED：** 以下仍在宿主执行：

- capability discovery、module import、module-level code 和 `register(api)`；
- `prepareArguments` 和 Pydantic/JSON Schema validation；
- extension registration 和 wrapper construction；
- `beforeToolCall` / extension `tool_call`；
- `afterToolCall` / extension `tool_result`；
- tool execution start/update/end 事件生成；
- AgentToolResult → ToolResultMessage；
- JSONL persistence；
- task/session lifecycle 和 abort 发起。

理由：这些是当前唯一 Pi loop、capability loader 与 extension runtime 的控制语义，并由 G3 明确作为可信宿主代码。搬入 worker 会复制第二套 package loader、Agent/extension/session runtime，既不符合架构契约，也没有可直接映射的 Poirot 父本。

---

## 6. Universal coverage 与不可绕过性

### 6.1 G1 锁定：production 全覆盖与 library 默认值

**RESOLVED：**

1. “所有 AgentTool 调用”是 `competitive_app` **production** 边界：凡 production wiring 驱动 Pi Agent 产生的 `AgentTool.execute()`，均必须经过注入的 sandbox executor，包括主 Agent、动态 tool set、extension tool 与 ephemeral sub-agent；不得按工具名或调用路径旁路。
2. `pi_agent` 作为可独立复用的 provider-neutral library，默认保留与 Pi upstream 同构的 `DirectToolExecutor`，以维持独立 library 的兼容性；安装或直接使用 `pi_agent` 本身不强制 Docker。
3. `competitive_app` production composition root 必须显式注入 sandbox executor。executor 缺失、误注入 `DirectToolExecutor` 或 sandbox 不可用都必须 fail closed；不得调用宿主 `tool.execute()`。
4. production 不得提供 direct fallback 的环境变量、配置开关、按 tool allowlist 或异常降级路径。G27 只允许 App tests 通过 Python 参数显式注入 Direct 或 test-local mock/spy；正常 dev server 仍只能 Docker。
5. 后续实施必须用 production wiring contract test 证明主 Agent、动态 tool、extension tool 和 ephemeral sub-agent 共用该不可绕过边界。

### 6.2 必须覆盖的路径（MUST）

1. sequential tool batch；
2. parallel tool batch；
3. `AgentHarness` 从 capability report 挂载的 tools；
4. workflow 动态执行 `agent.state.tools = ...` 后的 tools；
5. `CoverageEngine` ephemeral sub-agent tools；
6. `create_read_tool()` / `create_write_tool()` 等 harness tools（若被产品启用）；
7. extension `registerTool()` 后经 wrapper 得到的 tools；
8. 未来本地 `capability_packages/*` 注册的 tools；
9. HTTP session prompt 与 research task 两条产品调用路径；
10. resume 后重建 Harness 的调用路径。

### 6.3 不可用“按工具名白名单中间件”实现

Poirot 的 `SANDBOX_TOOL_NAMES` 模式只适合 sandbox-native façade。当前 feature 不应维护“这些名字进 sandbox、其他 passthrough”的集合；执行器必须是调用点级默认路径。

tool allowlist 仍然存在，但含义应是“Agent 可看见/可调用哪些 tool”，不能同时承担“哪些 tool 需要隔离”。生产可见的每个 tool 都必须隔离。

### 6.4 禁止隐式例外

锁定规则：

- 不得因工具“只是 HTTP”“只是 echo”“看起来纯函数”而跳过 sandbox；
- 不得按 provider、package 或 tool name 设置宿主 bypass；
- 系统内部非 AgentTool 的普通函数不因本 feature 自动进入 sandbox；
- 测试 fake/direct executor 必须通过 dependency injection 显式提供，不能由生产 env 静默选择。

---

## 7. Tool target 与 RPC 协议

### 7.1 G10 锁定：target metadata + approved registry

**RESOLVED：** runtime tool 携带 provider-neutral target metadata，production App 同时持有 immutable approved registry：

```python
@dataclass(frozen=True)
class ToolExecutionTarget:
    module: str
    qualname: str

@dataclass
class AgentTool:
    # existing upstream-compatible fields...
    executionTarget: ToolExecutionTarget | None = None
```

1. `executionTarget` 是明确的 Pi Python host delta，但属于 runtime metadata；`AgentTool.to_llm_tool()` 继续只输出 `name/description/parameters`，不得把 target 暴露给模型或 tool arguments。
2. capability loader 在 extension wrapper 之前从原始 execute callable 推导 target；`RegisteredTool.sourceInfo` 只用于验证 package provenance，不重复保存运行期 target。
3. `wrap_registered_tool()` 必须复制 `executionTarget`，并使用 `functools.wraps(original_execute)` 保留 callable lineage。
4. `competitive_app` production 在启动时从最终可见 tool bindings 构建 immutable approved registry；sandbox executor 必须验证 tool metadata 与 registry 中的 name/module/qualname binding 完全一致，不能只按 tool name 查找。
5. 动态 tool subset、workflow 替换和 ephemeral sub-agent 通过 `AgentTool` 自带 metadata 保持 binding；运行期新出现、缺 target、target 被替换或 registry 不匹配的 tool 必须 fail closed。
6. `pi_agent` standalone + `DirectToolExecutor` 不要求每个 tool 都有 target；该兼容性不得成为 `competitive_app` production 例外。

### 7.2 G11 锁定：可加载 target 集合

**RESOLVED：** production 只接受可重新 import 的 module-level `async def`；不使用 `pickle/cloudpickle`，不发送 callable bytecode 或任意 Python source。每个 production sandbox tool 必须解析为：

```json
{
  "module": "capability_packages.search_tavily.extensions.tavily_tools",
  "qualname": "_tavily_search_execute"
}
```

启动加载阶段必须验证：

1. loader 只沿显式 `functools.wraps` / `__wrapped__` lineage 还原原始 execute；最终对象必须满足 `inspect.iscoroutinefunction()`。
2. module 位于当前本地 capability package 或批准的 Pi harness tool 范围；worker image 内必须存在相同 module/qualname。
3. qualname 必须是可由 `importlib.import_module()` 重新解析的模块顶层函数，不含 `<locals>` / `<lambda>`，且解析结果仍是同一批准 binding。
4. closure、lambda、`functools.partial`、bound instance method、callable object、动态 source/eval 和同步函数全部拒绝，不为其增加序列化协议。
5. target 与 tool name 的 binding 唯一，target/code build identity 与宿主 approved registry 一致。
6. 最终 production visible tool set 中任一 target 不合格都必须使 App startup 失败；不得静默移除、pickle、host execute 或降级 Direct executor。
7. `pi_agent` standalone/Direct 路径可继续接收现有 Python callable 形状；G27 只允许 App tests 显式 DI 使用该路径，不提供 runtime config bypass。

### 7.3 G13 锁定：JSON worker bridge

**RESOLVED：** Poirot Docker/provider/runtime 负责容器执行基础设施；父本没有的任意 AgentTool bridge 使用最小 `agent-tool-rpc.v1` JSON envelope：

```json
{
  "protocolVersion": 1,
  "scopeId": "opaque-scope-id",
  "toolCallId": "call-123",
  "toolName": "tavily_search",
  "target": {
    "module": "capability_packages.search_tavily.extensions.tavily_tools",
    "qualname": "_tavily_search_execute"
  },
  "arguments": {"query": "example"}
}
```

禁止在 request 中携带：

- 任意 source code；
- 宿主绝对路径；
- 全量进程环境；
- Agent messages/system prompt；
- extension context/session manager/model registry；
- 与该 tool 无关的 secret。

G13 规则：

1. host/worker 只交换 UTF-8 JSON-compatible values；禁止 pickle/cloudpickle、Python object/bytecode/source、eval 和 `repr()` fallback。
2. request 必须带 protocol version、opaque scope id、tool call id、tool name、host-approved target 与已校验 arguments；target 不接受模型/tool arguments 提供。
3. JSON 编码拒绝 NaN/Infinity、bytes、自定义对象、非 string-key mapping 与重复 object key；不可序列化即 fail closed。
4. worker 只允许返回带相同 protocol/call id 的 JSON result 或脱敏 error；`AgentToolResult.details` 也必须 JSON-compatible。
5. partial update 是否以及如何跨容器传输由 G14 决定；abort/kill 由 G15 决定，不在 G13 偷渡 transport 方案。
6. request、单 frame、累计 update 与 final result 各以 `5 MiB UTF-8` 为上限，worker stdout/stderr diagnostic 合计上限 `10,000 bytes`；按 G24 fail closed，禁止静默裁剪合法 JSON。

### 7.4 G14 锁定：partial update 顺序

**RESOLVED：** 为保持 sandbox executor 与 Pi Direct executor parity，worker bridge 支持以下 JSON frame：

```text
update  → AgentToolResult partial
result  → AgentToolResult final
error   → {code, safeMessage, retryable}
```

协议要求：

- 每帧 JSON，带 protocol/call id 和单调递增 sequence；
- stdout/stderr 普通日志不得被误解析为 result；
- worker 每次调用 `on_update(partial_result)` 都产生一个 `update` frame，host 按 sequence/到达顺序调用既有 on-update callback，生成 `tool_execution_update`；
- final 只能出现一次；
- `result` 或 `error` 是唯一 final；final 前的 update 必须全部交付，final 后 update 忽略并记录 protocol diagnostic，与当前 Agent loop late-update 语义一致；
- `content/details/usage/addedToolNames/terminate` 保持当前字段；
- 非 JSON details fail closed，不做 `repr()` 悄悄降级；
- request、单 frame、累计 updates 与 final result 各不得超过 G24 锁定的 `5 MiB UTF-8`；worker stdout/stderr diagnostic 合计不得超过 `10,000 bytes`。

Poirot `DockerRuntime.exec_command()` 只在阻塞调用结束后返回最终 output，没有 partial/update 父本；本节属于必要 `NEW-HOST` bridge。具体承载 update frame 的 SDK stream、poll 或其他 channel 由后续 image/runtime 实测与 implementation plan 确定，不在 G14 宣称已 COPY。

### 7.5 G12 锁定：五参数 context-aware tool

当前 extension wrapper 可向接受第五参数的工具传 `ExtensionContext`。该对象含 session manager/model/signal/actions，不能直接跨进程。Poirot 同样不把 LangGraph Agent/runtime context 传入 container；其宿主 middleware 只以 `ContextVar` 传播 `sandbox_id`，sandbox tool 再通过 provider 取得窄 `Sandbox` facade。

**RESOLVED：**

1. production v1 只接受四参数 AgentTool execute，不支持需要第五参数 `ExtensionContext` 的 tool。
2. production loader 必须在 wrapper 前检查原始 callable signature；需要 context 的最终可见 tool 使 App startup 失败，不静默移除且不回退宿主。
3. v1 不定义 `SandboxToolContext`，不 RPC proxy session manager、model registry、Agent actions、abort/compact/shutdown 或任意宿主对象。
4. extension event handlers 继续按 G3 留在宿主；它们与 context-aware AgentTool execute 是不同边界。
5. worker request 只携带冻结的 JSON tool-call 数据；host context 不进入 container。
6. `pi_agent` standalone/Direct 路径继续保持当前五参数 wrapper 行为，维持 library parity。
7. 未来确有 JSON-only context 消费者时，必须另行 feature/protocol version bump + grilling，不在 v1 预留未验证协议。

---

## 8. 并行、abort、timeout 与生命周期

### 8.1 G16 锁定：同 scope 真并行

Poirot `DockerRuntime` 的单一 `threading.Lock` 会串行同 container 命令，不能直接用于 AgentTool transport。

**RESOLVED：** 同一 parent scope/container 内，Pi 标记为 parallel 的 AgentTool 调用必须真实重叠执行，不得因复制 Poirot 的 runtime 全局锁而退化为串行。

1. 一个 parent scope 复用一个逻辑 workspace；同一时刻的 tool call 复用该 scope 的 active container，不为每个 call 创建独立 container。
2. 每个 tool call 创建独立 shell/process worker session；parallel AgentTool 在同一 container 内由不同 worker process 并行运行。
3. sequential/parallel 分组和结果 source order 继续由 Pi Agent loop 决定；executor 不重排调用或结果。
4. Poirot provider/runtime/container backend 的结构与每次命令创建 SDK session 的控制流 `ADAPT`；`DockerRuntime.exec_command()` 的全局 `threading.Lock` 在 AgentTool 执行路径 `OMIT`。
5. 独立 worker process 与 async transport glue 是保持当前 production 并行行为所必需的最小 `NEW-HOST`；不得扩展成通用进程管理 API。
6. provider acquire/release 按 G23 绑定最外层 parent Agent run：首次 tool call lazy acquire，外层 `finally` 一次 release；单个 parallel call 和 ephemeral sub-agent 不得各自 release、回暖池或销毁共享 container。
7. contract test 必须用 barrier 与 wall-clock 同时证明至少两个 parallel tool 已同时进入 worker；只检查 `asyncio.gather()` 或结果正确不足以证明真并行。sequential tool 必须证明不重叠，parallel 结果仍按 source order 回填。

### 8.2 G15 锁定：scope-level abort

**RESOLVED：** 不新增 Poirot 不具备的 per-process PID/kill RPC；把当前 Pi/App abort 接到 Poirot 已有的 container destroy 路径：

```text
host signal aborted
  → scope 停止接受新调用/acquire
  → cancel host await
  → provider.destroy_scope(scope_id)
  → Docker stop + bounded inspect verification
  → Pi 产生 Operation aborted error result
```

约束：

1. abort 是 parent session/run 级语义；销毁 scope container 必须终止该 scope 内 main Agent 与 ephemeral sub-agent 的全部并行 tool call。
2. `destroy_scope()` 从 Poirot `_destroy_active()`、backend `destroy()` 与二次 discover guard `COPY/ADAPT` 为公开 provider operation；`AbortSignal → destroy_scope` 监听是最小 `NEW-HOST` glue。
3. 仅取消宿主 await、仅关闭 SDK/http client 或把 container 放回 warm pool 均不算 abort 完成。
4. destroy 后必须验证 container 已停止；失败则该 scope/container 不可复用且禁止回 warm pool，task 仍保持用户发起的 `aborted`；不新增 provider-wide unhealthy/circuit breaker。
5. workspace 按 G9 保留；resume 以同一 scope 创建新 container。
6. Docker stop 固定 `15s`，stopped inspect 固定 `5s`；G15 不引入 PID registry、per-call kill endpoint 或新进程控制协议。

### 8.3 G24 锁定：timeout / resource / size 默认值

Poirot frozen source 的真实默认只有：Docker runtime `no_change_timeout=1800s`、provider `idle_timeout=600s`、idle scan `60s`、`replicas=3`、readiness `60s`（单次 HTTP `5s`）、Docker stop `15s` 与 inspect `5s`。它不传 AIO `hard_timeout`，也没有 CPU、memory、PID、tmpfs、ulimit、workspace quota 或 universal JSON RPC byte limit。其 `bash` 只截断到 10,000 chars，`write_file` 单次 overwrite 上限 5 MiB，`download_file` 上限 100 MiB；这些是六个专用 façade tool 的限制，不是 universal AgentTool protocol。

AIO `v1.11.0` 自身的 Docker Compose 使用 4 CPU / 8 GiB / 2 GiB shm，公开 Kubernetes example 使用 1 CPU / 2 GiB limit；SDK shell 默认在 30,000 chars 截断，并原生支持但不默认启用 `hard_timeout`。本机锁定 digest 在禁用未使用 Browser/Jupyter/Code Server/MCP/VNC/Node REPL 后可 healthy，空闲采样约 169 MiB / 31 PIDs；未禁用 Browser 的原始 image 在同机 health 失败。该采样只证明 G17 derived image 必须禁用未使用服务，不作为跨平台容量承诺。

**RESOLVED：**

1. `COPY/ADAPT` Poirot 常量：`no_change=1800s`、`idle=600s`、idle scan `60s`、`replicas=3`、readiness `60s` / request `5s`、stop `15s`、stopped inspect `5s`。
2. `OMIT` global per-call hard timeout。Poirot 不使用它；当前 search adapters 已有 6s connect / 10s write / 120s read 与 Grok bounded retry，Pi/App 已有 abort。v1 不再增加第二套 wall-clock policy。
3. 仅为 G18 的已锁定 hardening 增加固定 Docker 常量：`cpus=1`、`memory=memory-swap=2 GiB`、`pids=128`、每个必要 tmpfs `256 MiB`、`nofile=1024`、`fsize=100 MiB`；它们不做 production tuning config。derived image 若在真实双平台 gate 不通过，按 G18 回开 G17，不静默放宽。
4. 仅为 G13 的已锁定 transport 边界增加固定常量：request、单 frame、累计 updates、final result 各 `5 MiB UTF-8`，worker stdout/stderr diagnostic 合计 `10,000 bytes`。SDK 调用必须关闭自身 30,000-char 截断，由 `agent-tool-rpc.v1` 按 bytes fail closed，禁止静默裁剪合法 JSON。
5. `OMIT` per-workspace aggregate quota。Poirot 没有该能力，当前唯一 bind mount 在 Docker Desktop/Linux 上也没有可直接复制的跨平台 directory-quota flag；v1 保留 fixed `fsize`、session-scoped retention 与显式 task delete，不造 quota watcher、loop filesystem 或磁盘 scheduler。
6. timeout / no-change / OOM / PID / fsize / protocol-size 必须映射为可区分的脱敏错误；不新增通用 resource telemetry service。

### 8.4 G6 锁定：逻辑 scope 粒度

**RESOLVED：**

1. 一个 parent `session_id` 对应一个稳定逻辑 sandbox scope；同一 session 的多轮 AgentTool 调用不得因 `task_id`、turn 或 `tool_call_id` 改变 scope。
2. 不同 parent session 必须使用不同 scope/workspace；禁止全局共享 sandbox。
3. research workflow 当前 task 启动后为 task↔session 1:1，resume 复用原 session；独立 `/sessions` 路径没有 task。因此 scope 以 session 而非 task 为产品级隔离键。
4. `task_id` 与 `tool_call_id` 只作为审计/调用定位 metadata，不参与 scope identity。
5. 逻辑 scope 与物理 container 生命周期解耦：container 可按 G23 warm/release/idle destroy 后重建，仍回到同一逻辑 scope；workspace 按 G9 跟随 parent session 生命周期。

### 8.5 G7 锁定：scope identity

**RESOLVED：** v1 直接适配 Poirot 的确定性 SHA-256 identity recipe，不引入 HMAC secret：

```python
sandbox_id = hashlib.sha256(
    b"agent-tool-sandbox-v1\0"
    + tenant_id.encode("utf-8")
    + b"\0"
    + parent_session_id.encode("utf-8")
).hexdigest()
```

1. 当前 App 无 auth/tenant identity，v1 固定 `tenant_id="local-default"`，并明确只承诺 single-tenant deployment 内的跨 session workspace 隔离，不宣称跨用户授权隔离。
2. `sandbox_id` 必须保留完整 64 位 lowercase hex；不复制 Poirot `sha256[:8]` 的 32-bit collision space。
3. Docker/container name、lock path 和 workspace path 只使用该 derived id，不使用 raw session id；只接受匹配 `^[a-f0-9]{64}$` 的内部值。
4. scope identity 只能由 App 在确认 parent session 存在后生成，不接受 HTTP、模型参数或 tool argument 直接提供 `sandbox_id`。
5. 未来引入 auth 后，App 必须先验证 session ownership，再传入经过认证的 canonical tenant identity；Pi executor 仍只接收 opaque scope id，不感知 auth policy。
6. 不使用 HMAC，避免新增 key persistence/rotation 和旧 workspace 恢复契约；若未来威胁模型要求不可枚举的 keyed identity，须另行 ADR/version bump。

### 8.6 G8 锁定：ephemeral sub-agent 继承

**RESOLVED：** 同一 parent session 下的 main Agent 与所有 ephemeral sub-agent 共享 parent sandbox scope/workspace。

1. App 必须把 parent session identity/derived opaque scope 显式传播到 ephemeral Harness/executor；不得用 `InMemorySessionRepo` 为 ephemeral agent 生成的临时 session id 创建新 scope。
2. 该行为复现 Poirot sub-agent 从 parent thread state 恢复 `sandbox_id` 的语义；当前仓不复制 LangGraph middleware，而通过既有 `build_ephemeral(..., session_id=...)` 架构边界适配。
3. 共享仅限 sandbox scope/workspace。ephemeral sub-agent 继续拥有独立 Pi Agent state、in-memory transcript、extension runtime 和 extraction lifecycle，不把它们合并进 parent Agent。
4. 不同 parent session 的 sub-agent 仍严格隔离；任何 sub-agent 层级都不得把 task id、ephemeral session id 或 tool call id 当作 scope identity。
5. 同 scope 的 parallel tool 按 G16 在同一 active container 的独立 worker process 中真实并行；它们共用 G23 的 parent-run acquire，不各自 acquire/release。

### 8.7 G9 锁定：workspace 生命周期

**RESOLVED：** workspace 跟随 parent session 生命周期，不设置独立时间 TTL，也不新增 retention scheduler。

1. research task `completed`、`failed` 或 `aborted` 后保留 workspace；resume 以原 session/scope 重新挂载同一 workspace。
2. App restart/shutdown、agent turn release 和 idle cleanup 只允许回收物理 container，不得删除 workspace。这与 Poirot 将 host workspace 独立于 container 生命周期的行为一致。
3. `DELETE /tasks/{id}` 必须先 abort 活动 task、停止接受新调用/acquire 并回收该 scope 的 worker/container，再把 workspace 纳入现有 JSONL + SOCM + session index cascade delete。
4. 独立 `/sessions` 当前没有 DELETE route；其 workspace 与 JSONL transcript 同生命周期持续保留。本 feature 不新增 session 删除 API。
5. workspace 删除只能使用 G7 derived 64-hex id 定位固定 sandbox root 下的目录，不接受 raw path/session/tool 参数。
6. v1 不提供 per-workspace aggregate quota；`fsize=100 MiB` 只限制单文件，不限制文件总数。磁盘增长由显式 task delete 控制并作为残余风险接受；不得用 container idle timeout 偷换 workspace retention，也不得新增 quota watcher、loop filesystem 或磁盘 scheduler。

### 8.8 G23 锁定：Poirot provider 生命周期

Poirot frozen SHA 的实际行为是：首次 sandbox tool 调用时 lazy `acquire()`，Agent run 的 `aafter_agent` 只 `release()` 一次；`release()` 关闭 runtime client 并把仍在运行的 container 放回以 `sandbox_id` 为键的 warm pool，不销毁 container。后续 acquire 依次查 in-process active、同 ID warm、cross-process discover/create。`replicas` 只在创建前驱逐最老 warm container，不强杀 active container；startup `list_running()` 把可连接 orphan 收进 warm pool；idle cleanup 覆盖 active + warm；shutdown 销毁两者。Poirot 没有 lease/refcount manager。

**RESOLVED：** 保留上述 provider lifecycle 与测试，但按当前 App 的 async/FastAPI 边界适配；不新增 per-call lease/refcount。

1. 每个最外层 parent Agent run 首次实际调用 tool 时 lazy acquire 同一 G7 scope；没有 tool call 的 run 不创建 scope container。
2. acquire 后，该 parent run 内 main Agent、所有已等待完成的 ephemeral sub-agent 和全部 parallel tool 共用同一个 active container；单个 tool call 和 sub-agent 不独立 acquire/release。
3. App 必须在包住完整 parent run 的 `finally` 中只 release 一次。当前 `SessionService.prompt()` 的 per-session lock、`AgentHarness.prompt()` 的 `wait_for_idle()` 与 CoverageEngine 对 sub-agent pool 的 await 提供这一外层边界；实施时只做对应 wiring，不加引用计数。
4. release 进入同 scope warm pool；后续同 scope 可健康检查后 reclaim。warm container 不跨 G7 scope 复用，workspace 仍按 G9 独立持久化。
5. 保留 Poirot replicas soft ceiling `3`：创建新 container 前只可驱逐最老 warm container；active container 不得为满足 replicas 被强制驱逐。
6. 保留 startup orphan reconciliation、active + warm idle cleanup 和 shutdown 全量 destroy；async 化并接入 FastAPI lifespan。`atexit`/SIGTERM/SIGINT/SIGHUP 独占 handler `OMIT`，不得与 App lifecycle 重复管理。
7. abort、unhealthy、idle 和 shutdown 的 destroy 路径必须从 active/warm cache 原子移除并保持 Poirot 的二次 discover 防误杀检查；G15 的 stopped verification 是已锁定 host delta。
8. `COPY/ADAPT`：三层 acquire、same-ID warm reclaim、soft replicas、release、orphan、idle、shutdown 及父本测试。`OMIT`：原草案提出但 Poirot 不存在、当前串行 run 边界也不需要的 per-call lease/refcount manager。

### 8.9 SoT 与持久化

锁定边界：

- tool call/result 对话史实仍只进 `data/sessions/` JSONL；
- sandbox workspace 是执行工件，不是对话 SoT；
- SOCM 仍是搜索 SoT；
- SQLite 仍是 App projection；
- container 可销毁，workspace 按 G9 独立于 container 生命周期并跟随 parent session；
- sandbox lifecycle 状态可以观测，但不得成为恢复 Agent transcript 的唯一依据。

---

## 9. Container 与安全基线（locked）

### 9.1 G17 锁定：pinned AIO-derived worker image

Poirot 本身不构建 sandbox image：仓内 `Dockerfile` 是完整 Poirot Agent image；`LocalContainerBackend` 只启动外部、未限定 registry/digest 的 `all-in-one-sandbox:latest`。其 production code 使用同步 `agent_sandbox.Sandbox`，集成测试也只验证可跳过的 `echo` 与文件读写。公开 AIO image 同时携带 Browser、Jupyter、Node.js、MCP、VSCode 等服务，且公开仓提供 SDK/client source 而不提供 server image Dockerfile；因此不能把 AIO image 当成可逐文件复制的 Poirot 父本。

**RESOLVED：** 不另写一套最小 sandbox HTTP server；保留 Poirot 的 AIO server/SDK transport，构建本项目拥有的薄派生 `pi4competitive-tool-worker` image：

- `FROM` 精确 AIO image digest，不接受未限定 registry 的 `all-in-one-sandbox:latest` 或裸 `latest`；
- 在 base 之上只新增 Python 3.12 tool worker、本仓锁定版本的 `earendil-works-pi-agent` 类型、approved capability code 和必要 provider dependencies；
- 不把 FastAPI、LLM provider、Agent loop、session/workflow 控制面加入 worker；AIO base 自带但未使用的服务是否可禁用/能否满足 hardening 由 G18 的真实 Docker gate 决定；
- host runtime `ADAPT` Poirot `DockerRuntime` 到精确版本的 `agent-sandbox` async client + 独立 shell session；G13/G14 的 JSON worker framing 仍是必要 `NEW-HOST`；
- amd64 + arm64 multi-arch；
- build 输出 digest/SBOM/provenance；
- production 配置只接受 digest，不接受裸 `latest`；
- host-worker 启动 handshake 校验 protocol 与 build identity。

G17 约束：

1. 不挂载 repo/code，不在 container startup/tool call 时 `pip install`，也不自建第二套 sandbox server。
2. derived image 只能新增 worker、approved capability code 及其精确依赖；不得把 FastAPI、LLM provider、Agent loop、session/workflow 控制面复制进 container。
3. host 通过 `agent-sandbox` async client 和每 call 独立 AIO shell session 承载 G16；G13/G14 JSON frame worker 是最小 `NEW-HOST`，不是第二套 HTTP server。
4. AIO base 自带的 Browser/Jupyter/Node.js/MCP/VSCode 等未使用服务不因此成为产品能力，也不得暴露给 AgentTool；可禁用范围和 hardening compatibility 由 G18 的真实 Docker gate 决定。
5. `agent-sandbox`、AIO server tag/base digest 与 derived image digest 的兼容 tuple 由 G22 锁定；G17 只决定 image/transport 路线，不授权浮动版本。

### 9.2 G18 锁定：Docker hardening

Poirot frozen code 的实际启动命令显式加入 `--security-opt seccomp=unconfined`，除此之外没有 container user、read-only rootfs、capability、no-new-privileges、PID/memory/CPU/ulimit 配置；单测还明确断言 `seccomp=unconfined` 存在。其 mount `read_only` 只约束单个 bind mount，不等于 read-only rootfs。调查时的 AIO `1.11.0` image OCI `User` 为空（`USER=gem` 只是环境变量），上游 compose 同样使用 `seccomp:unconfined`，仅另配 8 GiB memory 与 4 CPU。因此本节没有可直接 `COPY` 的安全 baseline。

**RESOLVED：** 下列 production baseline 全部作为 MUST：

```text
numeric non-root user:group
read-only root filesystem
size-capped tmpfs for required transient paths
cap-drop=ALL
no-new-privileges
Docker default or explicitly pinned reviewed seccomp (禁止 unconfined)
pids-limit
memory + memory-swap limit
cpus limit
ulimit nofile/fsize
loopback-only control port（若使用 HTTP）
never mount docker.sock
never use privileged, host PID/IPC, host devices or host network
```

G18 边界：

1. 这些限制不是新产品能力，而是 G1 fail-closed production sandbox、§4 威胁模型中宿主可用性/文件/daemon 保护所需的 container enforcement；缺任一项均不得宣称 production sandbox ready。
2. `LocalContainerBackend` 的 CRUD、参数组装和测试形状 `ADAPT`；删除 `seccomp=unconfined`，增加不可由普通 production config 关闭的 hardening 参数与 inspect/assert gate。不存在可复制的 Poirot hardening policy。
3. workspace 以外 rootfs 只读；必要写路径只能是 G19 批准的 scope workspace 或 G24 锁定的每路径 `256 MiB` capped tmpfs。
4. AIO 未使用服务应在 derived image/runtime 中尽可能禁用；但“禁用服务”不能替代 OCI/Docker enforcement。
5. derived image 必须在 Linux amd64 与 arm64 macOS Docker daemon（orbstack 实测，ADR 0011-A；与 Docker Desktop 同为 Linux VM daemon，无实质差异）真实执行 readiness、worker、parallel、no-change/abort 测试，并用 inspect 证明限制生效；只断言 command string 不算通过。
6. 若 G17 的 AIO-derived image 无法在上述 baseline 下工作，必须重新打开 G17 并改用可 harden 的 worker image；禁止以兼容 AIO 为理由放宽、隐藏或配置绕过任一 MUST。

### 9.3 G19 锁定：唯一 scope workspace mount

Poirot Docker backend 固定把 `<sandbox_root>/<sandbox_id>` 以 rw bind mount 挂到 `/mnt/poirot/user-data`，其 `DockerPathTranslator`、`DockerPathGuard` 和测试都围绕该 virtual prefix；这部分与 G6/G7/G9 的 per-session persistent workspace 可直接映射。另一方面，Poirot `SandboxConfig.mounts` → provider `_extra_mounts` → backend `create(extra_mounts=...)` 允许把任意配置的宿主路径以 ro/rw 方式加入 container，测试还明确覆盖 `/skills` extra mount；本仓 production 没有该需求。

**RESOLVED：** production sandbox 只允许一个 host bind mount：

```text
data/sandboxes/<full-64-hex-scope-id>/ → /mnt/poirot/user-data (rw)
```

直接保留 Poirot container virtual prefix，host root 则适配本仓 `data/` 布局。G19 规则：

1. `sandbox.root` 是 startup-only host 配置，默认 `data/sandboxes`；启动时解析为 canonical absolute root。每个 workspace 必须是该 root 下以 G7 full 64-hex id 命名的直接子目录，创建/复用/删除前拒绝 symlink、非目录和 containment mismatch。
2. production config 不提供 `mounts` / `extra_mounts` 列表；backend 收不到任意 host path、container path 或 ro/rw flag。固定 workspace mount 不能被 tool、HTTP、session metadata、capability 或环境变量追加/覆盖。
3. worker/capability code及依赖按 G17 baked into immutable image layers，不通过 source/repo mount 注入；临时文件只使用 G18 capped tmpfs 或当前 scope workspace。
4. G21 secret injection 不得新增持久 host bind mount；G26 若未来引入 artifact delivery，也必须在既有 scope workspace 内定义，不扩大 mounts。
5. `DockerPathTranslator` / `DockerPathGuard` 的 prefix、reverse mapping 和 traversal tests 优先 `COPY`；但 guard 只是 API 防御层，host isolation 必须由唯一 bind mount + G18 rootfs/OCI enforcement 证明。

禁止挂载：

- 仓库根目录；
- `.git`；
- `.env`；
- `data/app.db`；
- `data/sessions/`；
- Docker socket；
- 用户 home；
- 任何其他 host path，包括只读 source/skills/config mount。

Poirot fixed workspace bind/path mapping 为 `COPY/ADAPT`；`SandboxConfig.mounts`、provider `_extra_mounts` 和 backend 任意 extra-mount loop 在 production 为 `OMIT`；canonical root/child/symlink validation 是满足 S1–S4 所需的最小 `NEW-HOST`。

### 9.4 G21 锁定：Poirot container environment parity

Poirot `SandboxConfig.environment` 在 provider startup 复制为一个 container-level 字典，`LocalContainerBackend` 以 `docker run -e KEY=value` 注入，单测只验证普通 `NODE_ENV`；没有 per-tool secret scoping、短生命周期凭证、secret service、file/fd channel、rotation 或 secret redaction 父本。Poirot search 又绕过 sandbox，因此没有传 provider key 给 worker 的现成更细方案。

当前 Tavily/AnySearch/Grok execute 直接从 `os.environ` 读取配置。**RESOLVED：** 保持其代码不变，按 Poirot container environment 路径做最小适配：

1. App 固定允许传入现有七个 provider 配置名：`TAVILY_API_KEY`、`TAVILY_API_URL`、`ANYSEARCH_API_KEY`、`ANYSEARCH_API_URL`、`GROK_API_KEY`、`GROK_API_URL`、`GROK_MODEL`；只传宿主中实际存在的项。
2. 不传 `OPENAI_API_KEY`、模型 provider secret、全量 `os.environ`、`.env` 文件、App/DB/session 配置或其他 host variable。
3. 使用 Docker 原生 `--env NAME` 让 CLI 从自身环境继承值，避免把 secret value 拼进 argv；container 内仍是普通环境变量，现有 capability 无需改写。
4. 环境在 scope container 创建时固定，所有该 container 内的受信 tool process 都可读取所有已注入 provider 配置；v1 不做 per-tool 隔离。secret 变更需要销毁/recreate container，不新增热轮换协议。
5. request/update/result/error frame 不携带这些值；日志和异常不得主动输出值。Docker daemon/operator 可通过 inspect 看到 container env，按 Poirot 模型作为明确接受的残余风险。
6. per-call secret channel、临时文件、FD、sidecar/secret service、租约和自动 rotation 全部 `OMIT`。

Poirot `SandboxConfig.environment` → provider → backend env injection 控制流为 `COPY/ADAPT`；七项 App allowlist 是让现有 sandboxed tools 可运行所需的最小 wiring；不存在 `NEW-HOST` secret subsystem。

### 9.5 G20 锁定：Poirot network parity

Poirot `LocalContainerBackend` 只把 AIO control port 映射到 host `127.0.0.1`；它没有 `--network`、network lifecycle、egress allowlist、private/metadata deny 或相应测试。AIO 的可选 `PROXY_SERVER` 与 Browser URL allow/block API 也未被 Poirot sandbox wiring 使用，且不能约束当前 Python AgentTool 的 `httpx` socket。更关键的是，Poirot 的 `web_search` 根本绕过 sandbox，因此没有可移植的搜索 egress 父本。

当前本仓五个 search/fetch tool 的真实直连目标是窄集合：

- Tavily 只连接 `TAVILY_API_URL`（默认 `https://api.tavily.com`）的 `/search`、`/extract`；
- AnySearch 只连接 `ANYSEARCH_API_URL` MCP endpoint；
- Grok 只连接 `GROK_API_URL` 的 `/chat/completions`；
- Tavily/AnySearch fetch 的用户 URL 只作为 provider request JSON，由第三方 provider 抓取；container 不直连该 URL。这保持 frozen search feature F-S15 的“本地不验证 fetch URL、信任 provider”边界。

**RESOLVED：** 复制 Poirot Docker backend 的网络边界，不新增 egress security subsystem：

1. AIO control port 固定发布到 host `127.0.0.1`，production 不提供改成 `0.0.0.0` 的配置；这只保护入站 control API，不声称限制 container 出站。
2. 不创建 per-scope Docker network，不实现 egress gateway/proxy/firewall、provider allowlist、private/metadata deny、DNS/redirect policy或 network canary。
3. `docker run` 不指定 `--network`，沿用 Docker 默认 bridge 与默认公网 egress；仍遵守 G18 禁止 `--network=host`。
4. 不主动加入 AIO compose 的 `host.docker.internal:host-gateway`；若目标 Docker 平台自身提供网络可达性，v1 不额外治理。
5. Tavily/AnySearch/Grok 保持 frozen search feature 的 provider URL 与 `follow_redirects` 行为；不新增 endpoint scheme/address 校验。
6. G21 只解决 Poirot 已有的 secret/environment 传递边界，不以 secret 最小化为由偷渡网络 policy。

Poirot loopback port mapping 与默认 Docker network behavior 为 `COPY/ADAPT`；先前建议的 network lifecycle、gateway、allowlist、DNS/private/metadata enforcement 全部 `OMIT`，没有 `NEW-HOST` 网络模块。

### 9.6 G22 锁定：version tuple

Poirot frozen source 没有 lock file，声明 `agent-sandbox>=0.0.19` 并启动未限定 registry 的 `all-in-one-sandbox:latest`；unit tests mock SDK，Docker integration tests 可跳过且同样使用 `latest`，readiness 只检查 `/v1/sandbox` 返回 HTTP 200。实际代码向 `shell.exec_command()` 传 `no_change_timeout`，而 `agent-sandbox==0.0.19` 没有该参数；`0.0.30` 才具备该 API、async client、独立 session 和 hard timeout。调查时 AIO `1.11.0` 的 amd64/arm64 manifest-list digest 与 `latest` 相同。

**RESOLVED：** 只用现有 package lock + Docker digest：

```text
host SDK: agent-sandbox==0.0.30
AIO base: ghcr.io/agent-infra/sandbox@sha256:6328d7fd2f0ff0b4c147c3d05b3df1ce331f4a482eb6e550ecd64ed1fcf906e7
derived worker: <configured-registry>/pi4competitive-tool-worker@sha256:<build-output>
worker protocol: agent-tool-rpc.v1
```

1. `agent-sandbox==0.0.30` 进入本仓 `uv.lock`；不保留 `>=0.0.19`、range 或运行时 SDK fallback。
2. derived Dockerfile 以 manifest-list digest `FROM` AIO `1.11.0`，production 只接受构建后 derived image digest；tag 只作人类 provenance，不用于运行。
3. 不新增 version service、compatibility registry、自动更新器或协商协议。G5 已锁定的 startup readiness + worker canary 必须用这组 artifact 真执行 SDK shell session 和 `agent-tool-rpc.v1` handshake；失败即阻止启动。
4. future upgrade 显式同时修改 SDK pin/base digest、重建 derived digest 并重跑 G5/G16/G18 live gates；不在当前版本预留多版本兼容代码。

Poirot SDK/runtime/image config 与 readiness 流程为 `ADAPT`；loose range/`latest` 为 `OMIT`；uv pin、Docker digest 和既有 startup canary 足够，不新增版本管理模块。

---

## 10. 配置、启动与失败策略

### 10.1 G4 锁定：production provider

**RESOLVED：** `competitive_app` production v1 只允许 Docker sandbox provider/runtime。

1. production composition root 不得注册或选择 Poirot `LocalRuntime` / `LocalSandboxProvider`。
2. Docker daemon、image、provider 或 container 不可用时必须 fail closed；不得降级为 LocalRuntime、宿主 subprocess/FS 或 `DirectToolExecutor`。具体在启动期还是调用期失败由 G5 锁定。
3. production 配置不得接受 provider 字段、任意 provider class/import path 或 `local` fallback 开关；Docker provider 固定在 composition root。
4. G27 已锁定 `OMIT` LocalRuntime/LocalSandboxProvider/LocalSecurityGuard，即使测试也使用显式 protocol mock/spy。

### 10.2 G28 锁定：整版切换与最小配置面

Poirot frozen source 的实际行为是：`POIROT_SANDBOX_USE` 为空时整个 sandbox 不装配；非空时反射加载一个 provider；`SandboxMiddleware` 只把 `SANDBOX_TOOL_NAMES` 中的六个工具送入 sandbox，其余工具直接交回宿主 handler，单测明确要求 `web_search` 不 acquire sandbox。Poirot 没有 shadow/双跑对照、百分比流量、按 session 灰度、逐 tool 迁移、canary traffic、运行时迁移或回滚机制。

上述 disable switch 与 tool allowlist 无法映射到 G1/G4 已锁定的 production universal + fail-closed 契约；其余 rollout 能力父本不存在，当前架构也没有要求新增。**RESOLVED：** rollout 单位是应用版本，一次切换该版本的全部 production AgentTool：

1. 实现本 feature 的 production 应用版本只有 Docker sandbox execution 一条路径；不提供 runtime feature flag、kill switch、百分比/按 session/按 tool gate、shadow/dual execution、host comparison 或 Direct/Local fallback。
2. G5 startup readiness/canary 与既有 O*/L* 门禁在版本承接生产调用前完成；不新增 rollout controller、流量表、状态机、API 或 telemetry。
3. 回退只使用既有部署系统回滚到上一个应用版本；当前进程内不得切回 Direct executor。本文不新增或规定部署编排/流量切换机制。
4. production 配置不接受 `sandbox.enabled`、`sandbox.provider` 或 rollout 字段；Docker provider 固定在 composition root，非 secret 配置只保留 image digest 与 workspace root：

```yaml
sandbox:
  image: registry.example/pi4competitive-tool-worker@sha256:...
  root: data/sandboxes
```

5. G24 的 timeout/resource/size 数值继续是 v1 固定常量，不进入 production tuning config；G27 的显式 test DI 不构成 runtime rollout 面。

分类：Poirot `use` disable switch、反射 provider 选择和 `SANDBOX_TOOL_NAMES` bypass 均为 `OMIT`；父本不存在的 shadow/dual/percentage/session/tool rollout 同样 `OMIT`；只复用 G5 已锁定 readiness，不新增 `NEW-HOST` rollout 代码。

### 10.3 G5 锁定：启动 readiness

**RESOLVED：** production 必须在 FastAPI lifespan 进入 `yield` 前完成 sandbox eager readiness。

1. readiness 至少验证配置、Docker daemon/provider、配置镜像 identity、worker protocol/build handshake，并在隔离容器中运行最小 canary。
2. 任一步失败必须抛出 startup error，FastAPI 不进入可服务状态；不得启动为 degraded mode，也不得等第一条用户 tool call 才发现基础设施缺失。
3. canary 只验证共享基础设施，不要求提前创建每个 session 的 container；真实 scope container 仍可 lazy create 或从 Poirot warm pool acquire。
4. startup 失败必须 bounded cleanup 已创建的 canary/container、provider acquire 状态和 client；不能因 lifespan 尚未进入 `yield` 而遗留资源。
5. App 成功启动后发生的 Docker/provider/worker 故障仍 fail closed，并按 G29 生成现有 error tool result，不得 host fallback。

### 10.4 G29 锁定：运行失败语义

Poirot frozen source 的实际行为是：sandbox façade/runtime 将错误抛为 `SandboxError` 子类，外层 `ToolCallMiddleware.awrap_tool_call()` 捕获所有 `Exception` 并合成 `status="error"` 的 `ToolMessage`，Agent 可继续下一轮；它不按 trust/protocol/isolation 分类强制 task fail。Docker provider 也没有 provider-wide unhealthy 状态或 circuit breaker；`_drop_unhealthy()` 只在 acquire/reclaim health check 发现某个 cached/warm container 已死时移除并销毁该 container，runtime/tool 异常本身不会把整个 provider 标为 unhealthy。

当前 Pi 与此行为直接对得上：`_execute_prepared_tool_call()` catch-all 后生成 `isError=true` 的 `AgentToolResult`，保持 tool call/result 配对；只有异常逃出 Agent/ResearchRunner 时，App 才把 task 标成 `failed`。为保持 Poirot + Pi parity，**RESOLVED：**

1. 所有发生在一次 `AgentTool.execute()` transport 内的 sandbox acquire/runtime/worker/protocol/serialization/timeout/OOM/container-exit 异常，都转为现有脱敏 error tool result；不新增会绕过 Pi catch-all 的 fatal exception seam。
2. error result 明确表示本次 tool 未成功，不得 host fallback；Agent 可按既有语义换工具、重试或基于已有证据收尾。sandbox error 本身不强制 task fail；task 是否最终 failed 仍由既有 workflow 结果决定。
3. 只保留已锁定的边界例外：G5/G10–G12 的 startup/load/readiness 失败阻止 App 启动；G15 用户 abort 使 task aborted 并 destroy scope。它们不是 execute 期错误分类的新分支。
4. provider 只复制 Poirot 的 per-container health check + `_drop_unhealthy()`；不新增 provider-wide unhealthy mode、circuit breaker、fatal taxonomy、自动 task abort 或 sandbox 专属 retry controller。
5. capability 自身的 HTTP/auth/rate-limit 等错误继续保持现有脱敏 `AgentToolResult` 语义；RPC 非 JSON/超限/未知版本也只生成 error result，不使用 `repr()` 或接受部分结果。

分类：`SandboxError` 层级与 dead-container drop 为 `COPY/ADAPT`；落入现有 Pi error tool result 为架构映射；Poirot 不存在的 fatal sandbox taxonomy、强制 task-fail、provider-wide unhealthy/circuit breaker 全部 `OMIT`。

### 10.5 Shutdown

生命周期接入 `ApplicationState.shutdown()` / FastAPI lifespan：

1. 停止接受新调用/acquire；
2. abort/kill in-flight workers；
3. bounded wait；
4. destroy active + warm containers；
5. 关闭 SDK/http clients；
6. 保留或删除 workspace 按 G9；
7. 不依赖 `atexit` 作为唯一清理路径。

### 10.6 G25 锁定：审计与日志

Poirot frozen source 实际有两条不同路径：

1. sandbox `AuditGuard` 只对 shell command 做 block/warn/pass 分级；block/warn 写 Python warning，pass 写 debug，日志包含 command 前 100 chars。它的可选 journal event 为 `sandbox.command`，包含 command 前 200 chars，但 Docker provider 实际构造 `AuditGuard(DockerPathGuard())` 时没有传 journal；path validation 也只透传，不写审计。
2. Agent 层 `RunJournalMiddleware` 另行把完整 `tool_input` 与最多 2,000 chars output 写入 per-run events file，并配套 `RunActivityTracker`。这套代码依赖 LangChain/LangGraph，不属于 Docker sandbox provider；它也不是 sandbox isolation 的必要条件。

当前仓已经由 Pi 发出 `tool_execution_start/update/end`，并把 tool call/result 作为对话事实写入 session JSONL。现有 `task_spans` 只保存 LLM/sub-agent 的 kind/stage/model/token/latency 轻量 trace，没有 sandbox/tool audit schema。

**RESOLVED：**

1. `COPY` `AuditGuard` 及父本测试，Docker provider 与 Poirot 一样不注入 journal；保留其 command classification、logger level 与 journal failure 不影响执行的行为。
2. worker launch command 必须是无 arguments/result/secret 的固定命令；`agent-tool-rpc.v1` payload 不进入 shell command/argv，因此父本的 100/200-char command logging 不泄露 tool 内容。
3. `COPY/ADAPT` G23 provider 已有的 create/reclaim/release/destroy/unhealthy 日志；只记录父本本来就有的 sandbox/container lifecycle 信息，不额外增加 target、image digest、duration、resource code 等字段。
4. Pi 既有 tool events + session JSONL 继续作为 tool call/result 事实；不再复制一份 sandbox audit SoT。
5. `OMIT` Poirot `RunJournalMiddleware`、`RunJournal`、`RunActivityTracker`，以及此前候选的 sandbox audit table、task span 扩列、API、retention/export、完整 args/result logging。它们不是当前架构或已锁定 sandbox 边界所需。
6. G21/G13 的现有要求继续生效：provider secret、完整环境、RPC payload 和 worker stdout/stderr 不进入 host log；不新增独立 redaction framework。

### 10.7 G26 锁定：`present_files` / artifact delivery

Poirot frozen source 的 `present_files` 不是 sandbox provider lifecycle，而是一套额外产品能力：

1. `make_sandbox_tools()` 注册 `present_files`；tool 本身只检查 path string 以 `/mnt/poirot/user-data/` 开头并返回声明文本。
2. LangGraph `SandboxMiddleware` 识别该 tool，从 sandbox 反向解析 host path，把文件复制到全局 `.poirot/outputs/`，再把下载 URL 拼入 `ToolMessage`。
3. 独立 `ArtifactServer` 用 stdlib `ThreadingHTTPServer` 绑定 `127.0.0.1`，以 in-memory registry 暴露 `/artifacts/{sandbox_id}/{filename}`；无 auth、无持久 registry、无文件 size cap，读取时整文件进内存。
4. Poirot 另有报告 `LocalArtifactStore`，属于其 reporting 产品面，不是 Docker sandbox 的必需依赖。

当前 production AgentTool 只有 echo/search/fetch，不生成文件；本仓报告已经由 session JSONL + SOCM 保存并通过既有 report API 返回。G1 只要求现有 `AgentTool.execute()` 进入 Docker，不要求新增文件工具或下载协议。

**RESOLVED：**

1. `OMIT` `present_files` tool、middleware artifact branch、`ArtifactServer`、`LocalArtifactStore`、artifact state/reducer 及相关 reporting/multi-agent 代码。
2. v1 不新增 `.poirot/outputs`、文件复制、artifact registry、下载 HTTP route、URL 回写、preview、MIME/disposition 或 artifact retention。
3. G19 workspace 继续只是 session-scoped execution data；现有 report JSONL/SOCM/API 行为不变。
4. 将来确有文件产出型 AgentTool 时，另建 feature 定义授权、下载、大小、生命周期与跨 session 隔离；本 feature 不预留接口或空壳。

分类为纯 `OMIT`；没有 `COPY/ADAPT/NEW-HOST`。

### 10.8 G27 锁定：offline / dev / test executor

Poirot frozen source 的实际行为是：

1. `POIROT_SANDBOX_USE` 为空时整个 sandbox 关闭；非空时 `_load_sandbox_provider()` 反射加载任意 `module:Class`，可选择 `LocalSandboxProvider` 或 `DockerSandboxProvider`。LocalRuntime 会在宿主执行 subprocess/文件操作，不是隔离。
2. Poirot unit tests 大量显式构造 `MagicMock(spec=SandboxProvider/SandboxRuntime/...)` 测 facade、middleware、shutdown 和 provider 控制流；另有 LocalSandboxProvider 集成测试。
3. 真实 Docker integration test 单独依赖 Docker + `agent_sandbox`，依赖缺失时 module-level skip，并使用浮动 `latest`。

当前仓 G1 已锁定 `pi_agent` standalone 默认保持 upstream-compatible direct execution，G4/G5 已锁定 App production 只能 Docker 且 startup fail closed。现有 `USE_FAUX` 只替换 LLM provider；把它复用成 sandbox bypass 会混淆两条独立边界。当前 App offline tests 还会注入 closure 型 test tool，按 G11 它们只能走 test/direct 路径，不能伪装成 production remote target。

**RESOLVED：**

1. `packages/agent` 保留 G1 已要求的 `DirectToolExecutor`，作为 standalone library 默认和 parity test path；它是 upstream direct call 的最小 `NEW-HOST` seam，不进入 App production composition。
2. App offline/unit/integration tests 只能通过 Python constructor/function parameter 显式注入 `DirectToolExecutor` 或测试文件内定义的 mock/spy executor。缺少显式注入时，App composition 仍构建 Docker 并执行 G5 readiness。
3. 不提供 env/YAML/CLI `direct`、`fake`、`local`、`disabled` provider 选项；`USE_FAUX` 不改变 executor；正常 dev server 与 production 一样要求 Docker。
4. 不新增可发布的 `FakeToolExecutor` class/factory/package；测试按 Poirot 风格直接使用 protocol mock/spy，避免第二套运行时。
5. `OMIT` Poirot `LocalRuntime`、`LocalSandboxProvider`、`LocalSecurityGuard` 及任意 provider 反射加载，即使作为 parity/reference 也不落仓。
6. `COPY/ADAPT` Poirot 的 provider/runtime protocol-mock 单测形状；Docker 行为必须另有 pinned derived image live tests。ordinary offline CI 可跳 live test，但 P3.3 exit gate 仍必须保留真实 green 证据。
7. production wiring contract test 必须证明 HTTP/FastAPI lifespan 没有 Direct/Fake/Local 分支；测试显式 DI 不得通过 production config 或环境变量触达。

---

## 11. 分层与目标落点

### 11.1 依赖方向

```text
competitive_app.wiring
  → pi_agent.AgentToolExecutor protocol
  → competitive_app.adapter.out.sandbox implementation
  → Docker / agent-sandbox SDK

capability_packages/*
  → pi_agent.AgentTool
  ↛ competitive_app
```

约束：

- `packages/agent` 只拥有 provider-neutral executor contract 与 direct parity 实现；
- Docker、image、secret、mount、lifecycle policy 不进 `packages/agent`；
- `competitive_app.domain` 不 import sandbox SDK/IO；
- out adapter 不 import competitive domain；
- wiring 是 Pi protocol 与 sandbox adapter 的 composition root；
- worker 不 import FastAPI route/application workflow。

### 11.2 目标文件所有权

```text
packages/agent/src/earendil_works/pi_agent/
  tool_execution.py                 # NEW-HOST protocol + DirectToolExecutor
  agent_loop.py                     # minimal invocation seam
  agent.py / types.py               # executor + scope propagation
  harness/agent_harness.py          # parent scope binding
  extensions/wrapper.py             # preserve execution target

competitive_app/src/competitive_app/
  adapter/out/sandbox/
    contracts/
    docker/
    guards/
    runtimes/
    translators/
    exceptions.py
    sandbox.py
    types.py
    tool_executor.py                # AgentToolExecutor implementation
    worker.py                       # container-side RPC entrypoint
  wiring.py                         # config + injection + shutdown

deploy/tool-sandbox/
  Dockerfile
  entrypoint.sh                     # only if image requires it
```

最终文件名已由 implementation plan 在相同所有权内机械细化；本节已冻结模块边界，不授权创建第二 `pi_agent` 实现。

### 11.3 G2 锁定：双层归属、P3.3 统一交付

**RESOLVED：**

1. provider-neutral `AgentToolExecutor` seam、`DirectToolExecutor` parity 和 Pi tool-call 语义归 `packages/agent`，属于本仓 Pi engine enablement；这是需 ADR 列名的最小 host delta，不把 Docker 或 App policy 放入 Pi core。
2. Poirot sandbox facade、provider/runtime/backend、container lifecycle，以及 production fail-closed composition 归 `competitive_app` out adapter / wiring；它们属于 App 的基础设施实现，不进入 domain/application business logic。
3. 阶段归属锁定为 **P3.3**。P3.3 必须统一交付 Pi seam、App sandbox adapter 与 production 端到端门禁；只完成其中一层不得关闭阶段。P4 已有实现不回退，但在 P3.3 exit gate 前不得继续扩大依赖 AgentTool 的 P4 业务面。
4. transplant 以模块契约映射为先：职责、输入输出、控制流和生命周期均对得上时，默认近原样 `COPY`，只允许 import/package/license 等机械调整；宿主接口或架构契约确有差异时才 `ADAPT`，并逐项记录 host delta。
5. Poirot 没有对应模块时只允许实现满足 G1 和本仓架构契约所需的最小 `NEW-HOST` glue。implementation plan 必须逐文件证明为何不能 `COPY/ADAPT`；禁止在已有可映射父本时自行重写。

---

## 12. Poirot transplant map（frozen source map）

> 所有 source 均相对 Poirot `86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/`。G2 已锁定“映射对得上即优先 COPY”；implementation plan 必须遵守下表分类并逐文件记录机械调整与 host delta。

| Poirot source | 分类 | 本仓 target | 必要 host delta / 理由 |
|---------------|--------|-----------------|------------------------|
| `sandbox/exceptions.py` | `COPY` | `adapter/out/sandbox/exceptions.py` | import path only；保留错误层级和 details |
| `sandbox/types.py` | `ADAPT` | `adapter/out/sandbox/types.py` | 保留父本类型结构；`utc_now_iso` 改 stdlib；sandbox id 加长 |
| `sandbox/contracts/path_translator.py` | `COPY` | 同构 `contracts/` | import path |
| `sandbox/contracts/security_guard.py` | `COPY` | 同构 `contracts/` | import path |
| `sandbox/contracts/sandbox_runtime.py` | `ADAPT` | 同构 `contracts/` | 收窄为 async worker execution/update contract；G15 不加 PID/kill RPC；G26 已 OMIT 的 file façade API 不落仓 |
| `sandbox/contracts/sandbox_provider.py` | `ADAPT` | 同构 `contracts/` | async acquire/release；G7 scope key；公开 `destroy_scope()`；FastAPI lifecycle；不加 refcount |
| `sandbox/contracts/sandbox_backend.py` | `ADAPT` | 同构 `contracts/` | 保留 CRUD 职责；增 hardening/resource config |
| `sandbox/sandbox.py` | `ADAPT` | `adapter/out/sandbox/sandbox.py` | 保留 validate→translate→execute→mask 主链并收窄到 worker command；G26 file façade methods OMIT |
| `sandbox/translators/docker_path_translator.py` | `COPY` | 同构 `translators/` | 保留 fixed virtual prefix、identity translate 与 host reverse mapping |
| `sandbox/translators/identity_translator.py` / `local_path_translator.py` | `OMIT` | — | Docker provider 已使用 DockerPathTranslator；不复制 Local/E2B test path |
| `sandbox/guards/audit_guard.py` | `COPY` | 同构 `guards/` | Docker 路径与父本一样不注入 journal；worker command 固定且不携带 RPC payload/secret |
| `sandbox/guards/docker_path_guard.py` | `ADAPT` | 同构 `guards/` | 保留父本 guard 主链；prefix 改本仓；补 traversal/worker request path rules |
| `sandbox/guards/local_security_guard.py` | `OMIT` | — | G27 不复制 Local test runtime；Docker production 使用 DockerPathGuard + AuditGuard |
| `sandbox/guards/permissive_guard.py` | `OMIT` | — | production 不应以 permissive guard 冒充安全策略 |
| `sandbox/utils/sandbox_id.py` | `ADAPT` | `utils/sandbox_id.py` | 保留确定性 SHA-256；输入映射为 version + tenant + parent session；8 hex 改完整 64 hex；不加 HMAC |
| `sandbox/utils/file_operation_lock.py` | `OMIT` | — | 只服务已由 G26 OMIT 的 `str_replace` file tool；worker bridge 不预留 staging lock |
| `sandbox/utils/search.py` | `OMIT` | — | 只服务已由 G26 OMIT 的 file grep/list 产品能力 |
| `sandbox/docker/executor.py` | `ADAPT` | `docker/executor.py` | 保留 Docker CLI executor；OMIT WSL/Apple Container 分支，目标平台仅 Linux Docker 与 Docker Desktop |
| `sandbox/docker/cross_process_lock.py` | `COPY` | `docker/cross_process_lock.py` | lock key/path 适配 |
| `sandbox/docker/readiness.py` | `ADAPT` | `docker/readiness.py` | 保留 polling 控制流；async only；校验 protocol/build identity，不只 HTTP 200 |
| `sandbox/docker/local_container_backend.py` | `ADAPT` | `docker/local_container_backend.py` | pinned AIO-derived worker image；移除 seccomp=unconfined；加 user/cap/resource/network/read-only/digest |
| `sandbox/docker/docker_sandbox_provider.py` | `ADAPT` | `docker/docker_sandbox_provider.py` | 保留三层 acquire、same-ID warm、soft replicas、orphan/idle/shutdown；parent run 一次 acquire/release；移除独占 signal handler；不加 refcount |
| `sandbox/runtimes/docker_runtime.py` | `ADAPT` | `runtimes/docker_runtime.py` | sync→async；每 call session；update polling/stream；abort 交 provider destroy scope，不加 per-process kill；精确 SDK 版本 |
| `sandbox/runtimes/local_runtime.py` | `OMIT` | — | 宿主 shell/FS 不是隔离；测试 direct executor 另走显式 dependency injection |
| `sandbox/local/local_sandbox_provider.py` | `OMIT` | — | G27 不复制 Local provider，即使测试也使用 protocol mock/spy |
| `sandbox/integration/config.py` | `ADAPT` | App config/wiring | Pydantic/settings；封闭 provider；secret 分离 |
| `sandbox/integration/bootstrap_sandbox.py` | `ADAPT` | `ApplicationState.shutdown` / lifespan | 不以 atexit 为唯一清理 |
| `sandbox/integration/context.py` | `OMIT` | — | 当前项目通过既有 session/Harness/wiring 显式传播 scope；不复制 LangGraph ContextVar state |
| `sandbox/integration/tools.py` | `OMIT` | — | 不新增六个 Poirot product tools；目标是已有 AgentTool universal execution |
| `middlewares/sandbox_middleware.py` | `OMIT` | — | LangChain/LangGraph + tool-name allowlist 均不适用 |
| `artifacts/server.py` / `artifacts/local_store.py` | `OMIT` | — | `present_files`/report delivery 是额外产品面；当前无文件产出型 AgentTool，不新增下载 server/store |
| `sandbox/docker/remote_container_backend.py` | `OMIT` | — | K8s 空壳不进 v1 |
| `multiagent/*sandbox*` | `OMIT` | — | 当前 sub-agent 已在本进程 Pi runtime；只共享 scope id |
| — | `NEW-HOST` | `pi_agent/tool_execution.py` | upstream 无 executor seam；ADR 明示最小 host delta |
| — | `NEW-HOST` | `adapter/out/sandbox/tool_executor.py` | AgentTool target → sandbox worker RPC |
| — | `NEW-HOST` | `adapter/out/sandbox/worker.py` | import approved target + async execute + JSON frames |
| — | `NEW-HOST` | `deploy/tool-sandbox/Dockerfile` | reproducible pinned multi-arch execution environment |

### 12.1 明确禁止的“照抄”方式

1. 不复制 Poirot 的 LangChain/LangGraph imports。
2. 不复制 `SANDBOX_TOOL_NAMES` 按名字选择性绕过。
3. 不复制 LocalRuntime 并在 production 称为“沙箱”。
4. 不复制 `seccomp=unconfined`、浮动 image tag 或全量 environment 注入。
5. 不因 transplant-first 保留会破坏 parallel/abort/asyncio 的同步锁与阻塞调用。
6. 不复制 TUI、artifact server、MCP、specialist、多 agent runtime 或 K8s 空壳。
7. 不把 Docker policy 放进 Pi Agent core。

---

## 13. 架构契约变化（ADR 0011 accepted）

### 13.1 D1 进程拓扑

锁定修订：

> FastAPI、Pi Agent、LLM、Session 与 Application Process Manager 保持单一 Python 控制进程；本地 AgentTool 数据面必须在隔离 sandbox worker/container 中执行。sandbox worker 不得包含第二 Agent/LLM/workflow 内核。

这保留“无 Node+FastAPI 双 Pi、无第二 Agent 内核”的原意，但明确允许安全执行基础设施进程。

### 13.2 D6 执行面

锁定修订：

> capability package 内 tools/extensions 仍为 Python；AgentTool callable 可由宿主加载元数据，但其 production `execute()` 在固定 Python sandbox image 内运行。禁止嵌 Node 执行 TS package。

### 13.3 D9 / D10 ownership

- sandbox lifecycle 和 transport 是 App out adapter / wiring IO；
- Domain 不接触 Docker/SDK；
- Application Process Manager 只持 executor port，不实现 Docker CRUD；
- tool business logic 仍在 `capability_packages/*`。

### 13.4 D14 / G4 Pi parity

- Pi upstream 仍是 Agent loop、events、tool result 语义 SoT；
- `AgentToolExecutor` 是一项列名 host delta；
- `DirectToolExecutor` 与当时 upstream direct call 建 parity test；
- sandbox implementation 不得演化成第二 loop。

### 13.5 G2 锁定阶段

```text
P1 → P2 → P3 → P3.1 → P3.2 → P3.3 AgentTool sandbox → continue P4
```

P4 已有实现不回退；但在 P3.3 exit gate 前暂停继续扩大依赖 AgentTool 的 P4 业务面。该阶段归属已由 ADR 0011 + 0011-A、架构契约 v0.3.8 与 Roadmap 锁定；运行时代码只能按 active implementation plan 推进。

---

## 14. 验收门禁（locked）

### 14.1 Offline / contract

| ID | 验收 |
|----|------|
| O1 | Spy executor 证明 sequential、parallel、dynamic tools、main Harness、ephemeral sub-agent、resume 全部经过同一 executor seam |
| O2 | `DirectToolExecutor` 对照当前 Pi upstream：结果、异常、partial update、terminate、addedToolNames 行为一致 |
| O3 | `prepareArguments`、validation、before/afterToolCall、extension tool_call/tool_result 与 tool execution events 顺序不变 |
| O4 | wrapper 保留 `executionTarget`/callable lineage；缺失或 registry 不匹配的 target，以及非 importable closure、未批准 module/qualname、target collision，均在 production load/startup fail closed |
| O5 | worker request/update/result/error 协议 roundtrip；未知版本、重复 final、late update、非 JSON/超限均拒绝 |
| O6 | parallel 两工具真实重叠执行，结果仍按 source order 回填；sequential 不重叠 |
| O7 | Pi/App abort 会阻止新调用/acquire、销毁并确认该 scope container 停止；只取消 host await、关闭 client 或 release warm 不算通过 |
| O8 | timeout/OOM/container exit/SDK error 转脱敏结构化错误，且永不调用 host tool.execute |
| O9 | research task 与独立 session 路径都以 parent session 绑定 scope；ephemeral sub-agent 继承 parent scope 而忽略自身临时 session id；不同 parent session 隔离 |
| O10 | parent run 只 acquire/release 一次；parallel tool/sub-agent 无提前 release、double close 或共享 container 误杀 |
| O11 | warm pool、idle cleanup、orphan discover、application shutdown 行为可重复且无遗留 active container |
| O12 | JSONL tool call/result、SOCM、SQLite projection 的既有 SoT/顺序不变；sandbox state 不是 resume 唯一依据 |
| O13 | config missing/invalid image identity/readiness/protocol mismatch 按 G5 在 lifespan `yield` 前 fail startup，并清理 partial-init 资源 |
| O14 | `packages/agent` 不 import Docker/competitive_app；Domain 不 import sandbox SDK；无 LangChain/LangGraph |
| O15 | 每个 COPY/ADAPT 文件含 Poirot SHA/path/MIT notice/host delta；SDK Apache-2.0 notice 完整 |
| O16 | CodeGraph impact + affected tests、全仓 offline、Pi contract-drift、search/Reasonix co-load 均绿 |
| O17 | production loader 对第五参数 context-aware tool fail startup；standalone Direct executor 的既有五参数 wrapper parity 不变 |

### 14.2 Security

| ID | 验收 |
|----|------|
| S1 | 工具不能读取/修改 sandbox mount 外的宿主 canary 文件 |
| S2 | scope A 不能读取 scope B workspace；并发/重启/ID 构造下仍成立 |
| S3 | container mounts 不含 repo、`.git`、`.env`、app.db、sessions、home、docker.sock |
| S4 | path traversal、symlink、absolute path、redirect/worker staging escape 均不能越过允许 mount |
| S5 | container 只收到 G21 固定七项中宿主实际存在的配置，LLM/full env 不进入；request/result/error/log/span/docker argv 不含 secret value；不虚假声称 scope 内 per-tool isolation 或 Docker inspect 隐藏 |
| S6 | sandbox/provider/worker 故障时无 host fallback；用 host canary side effect 证明 |
| S7 | production 只接受 digest；host-worker protocol/build mismatch 拒绝执行 |
| S8 | G24 的 CPU/memory/PID/tmpfs/fsize/RPC/log/no-change 限额真实触发并回收，不只测 config 字符串；不得声称存在 aggregate workspace quota |
| S9 | abort 后 scope container 已停止且无后台 orphan process；workspace 按 G9 保留并可在新 container resume |
| S10 | non-root、cap-drop、no-new-privileges、seccomp、read-only rootfs 生效；无 privileged/docker.sock |
| S11 | 网络行为符合 G20：AIO control port 只绑定 host loopback，未使用 host network/显式 host-gateway；现有 provider live call 经 Docker 默认 egress 成功；测试与文档均不虚假声称 egress 隔离 |
| S12 | G7 recipe 产生稳定 64-hex id；同 session 重启一致、不同 session 隔离；raw/非法 scope 输入不能路径穿越或命令注入；v1 不虚假声明多租户授权隔离 |

### 14.3 Docker / live

| ID | 验收 |
|----|------|
| L1 | production lifespan readiness/canary 真实通过；`echo` 全栈运行并返回 container identity 证据；宿主 spy 证明 callable 未执行 |
| L2 | `tavily_search/fetch`、`anysearch_search/fetch`、`grok_search` 从 production image 真调用 provider 成功 |
| L3 | 完整 research workflow：main Agent + parallel ephemeral sub-agents 共享 scope，搜索结果/SOCM/report 正常 |
| L4 | 真实 parallel wall-clock、partial update fixture、abort、no-change timeout、container crash recovery 全绿 |
| L5 | completed/failed/aborted、App restart/resume、warm reclaim、explicit task delete、shutdown 后 container/workspace 行为符合 G9/G23；idle cleanup 不删除 workspace |

### 14.4 G30 锁定：性能边界

Poirot frozen source/tests 没有 cold/warm start、单调用 overhead、throughput、P50/P95 或 load benchmark。其唯一真实 Docker integration 只断言 create/readiness、`echo`、file read/write、alive/discover 成功；Docker/SDK 缺失会 module-level skip，60s 内未 ready 也直接 skip，不记录或断言耗时。unit tests 使用 mock SDK；并发测试只验证 provider/thread safety，`DockerRuntime.test_serial_lock` 反而明确断言同 runtime 命令被全局锁串行。父本中的 timing 值只有 G24 已复制的 readiness/no-change/idle/stop 等 lifecycle timeout，不是性能 SLA。

本仓目前也没有 sandbox runtime 可供诚实测 baseline；既有 `task_spans.latency` 只属于 LLM/sub-agent trace，G25 已锁定不为 sandbox 增字段。当前架构和已锁定需求只要求：G5 readiness、G16 真并行、G23 warm reclaim 和 L1–L5 真实功能通过，没有用户可见 latency SLO。**RESOLVED：**

1. v1 不冻结 cold/warm、单调用、P50/P95、throughput 或 4-way speedup 数值，不新增 benchmark harness、load test、性能 CI、sandbox latency telemetry/span 或 tuning config。
2. 保留既有功能门禁：G5 在 G24 的 60s readiness 边界内完成 startup canary；G16 用 barrier + wall-clock 只证明 parallel 调用确实重叠且不被全局锁串行，不把 wall-clock 变成绝对延迟 SLA；G23 验证 same-scope warm reclaim，不要求比 cold start 快多少。
3. L1–L5 继续要求 pinned derived image 在真实 Linux amd64 与 arm64 macOS Docker daemon（orbstack 实测，ADR 0011-A）上功能全绿；测试耗时只作为诊断输出，不作为 pass/fail 门槛，也不得因慢而 host fallback。
4. cold start/worker overhead 作为已知残余风险如实保留；只有出现明确产品 latency 需求或真实测量问题后，才另建性能 feature，不在 sandbox v1 预留接口。

分类：Poirot warm pool/readiness/功能集成测试已分别由 G23/G5/L* `COPY/ADAPT`；父本不存在的性能 SLA、baseline suite、telemetry 与调优面全部 `OMIT`，无 `NEW-HOST` 性能模块。

普通 CI 可将依赖 Docker/provider secret 的 L* 标记为 live，但关闭 P3.3 必须留存真实 green 证据；skip 不能关闭阶段。

---

## 15. 已知风险与必须诚实保留的残余风险

| 风险 | 当前处理方向 |
|------|--------------|
| Poirot 只隔离六个 façade tools | 新增 universal executor；不复制按名字 passthrough |
| Pi upstream 无 executor seam | ADR 明示最小 host delta + direct parity test |
| worker/host code version skew | image digest + protocol/build handshake |
| current extension wrapper 丢 callable target | 显式 execution target registry / wraps；load-time validation |
| context-aware tool 不能序列化 | v1 reject 或冻结 JSON-only context；不 proxy 任意宿主对象 |
| AIO SDK/image API 漂移 | pin compatibility tuple；不使用 `>=` + `latest` |
| Poirot sync lock 破坏并行 | async per-call process session；lifecycle 只在 parent run 外层 acquire/release |
| Docker 默认 egress 可访问非预期网络目标或用于 exfiltration | G20 明确接受 Poirot parity 残余风险；不新增网络子系统，G21 仅处理已确认的 secret 传递边界 |
| 同 scope tool 可读取全部已注入 search provider 配置，Docker operator 可 inspect | G21 明确接受 Poirot container-env parity；只隔离 LLM/full host env，不新增 per-tool channel/rotation |
| Docker 不是 VM/kernel zero-day boundary | hardening + threat-model wording；不做绝对隔离宣传 |
| cold start/worker overhead | 复用 Poirot warm pool；v1 不设性能 SLA，残余风险如实保留且不以 host fallback 优化 |
| sandbox workspace 变成隐式 SoT | JSONL/SOCM/SQLite 职责不变；workspace retention 单独约束 |
| Docker Desktop/orbstack / arm64 差异 | multi-arch image + macOS arm64 real gate（orbstack 实测，ADR 0011-A） |
| local test 为方便绕过 sandbox | direct/fake 只能显式 DI；production wiring contract test |

---

## 16. Grilling 决策队列（G1–G30 resolved）

`grilling` 已按 G1→G30 一次一题完成；全部决策均为 RESOLVED，implementation plan 不得重新解释或扩大。

从 G13 起，每题推荐前必须先读取 Poirot frozen SHA 的相关实现与测试，而不是只看其文档，并按以下顺序报告：Poirot 实际行为与限制 → 本仓模块/契约能否映射 → `COPY/ADAPT/OMIT/NEW-HOST` 分类 → 推荐答案。Poirot 没有对应能力时必须明确写“父本不存在”，不得把新设计描述成移植；还必须先证明该能力由现有架构契约、生产行为或已锁定需求要求，否则默认 `OMIT`，不得因“未来可能有用”新增实现。

G20 grilling correction 后进一步锁定：Poirot 没有且用户未明确提出的能力，即使属于通用 hardening 建议，也不得仅凭“更完善”加入；除非能指向现有架构/生产语义/已锁定决定的直接强制要求，否则答案必须是 `OMIT`。

| ID | 问题 | 当前推荐答案 | 状态 |
|----|------|--------------|------|
| G1 | “所有 AgentTool”覆盖 `competitive_app` production，还是连 `pi_agent` 作为独立 library 的默认执行也强制 Docker？ | App production 必须显式注入 sandbox executor 且无 direct fallback；`pi_agent` library 默认保留 upstream-compatible Direct executor | **RESOLVED** |
| G2 | 归属 P3.3 并在继续 P4 前关门，还是作为 P4 out-adapter feature？ | 双层归属、P3.3 统一交付：Pi 拥有 provider-neutral seam；App 拥有 Poirot sandbox adapter/wiring；模块契约匹配时优先 COPY | **RESOLVED** |
| G3 | 只隔离 `AgentTool.execute`，还是连 register/prepareArguments/extension handlers 也进容器？ | 只隔离 execute；其余作为可信代码留在唯一 Pi 控制面；加载期 supply-chain 风险明确不由本 feature 防护 | **RESOLVED** |
| G4 | production provider 是否只允许 Docker？ | 是；Docker 不可用时 fail closed，禁止降级 LocalRuntime、宿主 subprocess/FS 或 Direct executor | **RESOLVED** |
| G5 | sandbox 基础设施不可用时启动失败还是首个 tool call 才失败？ | lifespan eager readiness/canary 失败即启动失败并清理 partial-init；scope container 可 lazy/warm | **RESOLVED** |
| G6 | sandbox scope 是每 tool call、每 task、每 parent session 还是全局？ | 每 parent session 一个稳定逻辑 scope/workspace；物理 container 可 release/destroy/recreate | **RESOLVED** |
| G7 | 在当前无 auth/tenant 字段时如何构造 scope；未来怎样防跨租户？ | 适配 Poirot SHA-256：`version + local-default + parent session` 完整 64 hex，不加 HMAC；未来先验 session ownership 再注入 canonical tenant identity | **RESOLVED** |
| G8 | ephemeral sub-agent 是否共享 parent sandbox？ | 是；继承 parent scope/workspace，忽略自身 in-memory session id；Agent state/transcript/extension runtime 仍独立 | **RESOLVED** |
| G9 | workspace 在完成、失败、abort、delete、resume 后如何保留/删除？ | 跟随 parent session 生命周期、无独立 TTL；完成/失败/abort/restart 保留，resume 复用，显式 task delete 随 session cascade 删除 | **RESOLVED** |
| G10 | remote target 放 `AgentTool` 字段、RegisteredTool metadata 还是独立 registry？ | `AgentTool.executionTarget` runtime metadata + App immutable approved registry；wrapper 保留，RegisteredTool 只供 provenance，不进入 LLM schema | **RESOLVED** |
| G11 | closure/lambda/dynamic callable 如何处理？ | production 只接受可重新 import 的 module-level async function；其余启动失败，不 pickle、不静默移除、不 host fallback | **RESOLVED** |
| G12 | 接受第五参数 `ExtensionContext` 的 tool 如何处理？ | production v1 拒绝并 fail startup；不定义 context RPC/proxy；host extension handlers 与 standalone Direct 五参数 parity 保留 | **RESOLVED** |
| G13 | RPC serialization 和大小边界是什么？ | 父本不存在的最小 `agent-tool-rpc.v1` JSON bridge；禁止 Python object/source/pickle；非 JSON fail closed；各类 RPC 5 MiB、diagnostic 10,000 bytes | **RESOLVED** |
| G14 | `on_update` 如何跨容器？ | Poirot 无父本；worker 发有序 JSON update，再发唯一 final；host 保持 Pi update/late-update 语义，具体 carrier 留实测/plan | **RESOLVED** |
| G15 | abort 的完成定义是什么？ | 不加 per-process kill RPC；Pi abort 触发 Poirot provider scope-level container destroy + bounded stop verification，workspace 保留 | **RESOLVED** |
| G16 | parallel tool 是否必须在同 container 真并行？ | 是；同 active container 独立 worker process 真并行，Pi 保持 source-order；Poirot runtime 全局锁在 AgentTool 路径 OMIT | **RESOLVED** |
| G17 | 直接使用 AIO image/SDK，还是构建最小自有 worker image？ | 保留 AIO server/SDK，构建 pinned AIO digest 之上的薄派生 multi-arch worker image；不直接跑 latest，不另写 sandbox server | **RESOLVED** |
| G18 | Docker hardening baseline 是否全部作为 MUST？ | 全部 MUST；真实 Docker + inspect gate；AIO 不兼容则回开 G17，不允许降级 privileged/root/unconfined | **RESOLVED** |
| G19 | 允许哪些 mounts？ | 仅 `data/sandboxes/<64hex>` → Poirot `/mnt/poirot/user-data` rw；production 无 extra-mount 配置；代码 baked image；其余 host path 全禁 | **RESOLVED** |
| G20 | 网络 egress 到什么强度？ | 复制 Poirot：control port 仅 host loopback，Docker 默认 bridge/egress；不新增 network/gateway/allowlist/private deny；残余风险明示 | **RESOLVED** |
| G21 | provider secrets 如何注入？ | 复制 Poirot container env：仅按固定七项名称继承现有 search provider 配置，scope 内共享；不传 LLM/full env；不做 per-tool channel/rotation | **RESOLVED** |
| G22 | `agent-sandbox` 与 server image 如何版本化？ | `agent-sandbox==0.0.30` + AIO 1.11.0 manifest digest + derived image digest；复用 G5 canary，无版本服务/fallback | **RESOLVED** |
| G23 | 是否保留 Poirot warm pool、replicas、orphan reconciliation？ | 保留三层 acquire、same-ID warm、soft replicas、orphan/idle/shutdown；适配 FastAPI async lifecycle；parent Agent run 外层一次 acquire/release，OMIT per-call lease/refcount | **RESOLVED** |
| G24 | timeout/CPU/memory/PID/output/workspace 的默认值？ | 复制 Poirot lifecycle/timeout 常量；OMIT global hard timeout 与 aggregate workspace quota；仅为 G18/G13 固定 1 CPU/2 GiB/128 PID/256 MiB tmpfs/ulimit 与 5 MiB RPC/10,000-byte log，不开放 tuning config | **RESOLVED** |
| G25 | 审计记录哪些内容，如何脱敏？ | 只 COPY `AuditGuard` + provider lifecycle logger；Pi events/JSONL 保持现有 SoT；OMIT RunJournal/ActivityTracker、新 audit store/API/span 字段与 args/result logging | **RESOLVED** |
| G26 | v1 是否新增 present_files/artifact delivery？ | 不新增；OMIT tool/middleware branch/ArtifactServer/store/state/reporting；当前 report API 不变，未来文件交付另 feature | **RESOLVED** |
| G27 | offline/dev/tests 是否允许 Direct/Fake executor？ | Pi standalone 保留 Direct；App tests 仅显式 Python DI Direct 或 test-local mock/spy；OMIT Local/Fake runtime 与配置开关，dev/production 始终 Docker | **RESOLVED** |
| G28 | rollout 是 feature flag/按 tool 灰度，还是一次切全量？ | 以应用版本一次切换全部 production AgentTool；OMIT runtime flag/kill switch/shadow/dual/百分比/session/tool gate 与 host fallback；回退只走既有版本回滚 | **RESOLVED** |
| G29 | sandbox infra/tool worker 错误应只产 error tool result，还是直接使 task 失败？ | 复制 Poirot/Pi catch-all：全部 execute 期错误转现有 error tool result；不新增 fatal taxonomy、强制 task-fail 或 provider-wide unhealthy；startup fail 与 abort 沿用已锁定边界 | **RESOLVED** |
| G30 | 可接受的冷启动、单 call 开销和并行性能门槛？ | Poirot 无性能 SLA；OMIT P50/P95、cold/warm/throughput 数值、benchmark/telemetry/tuning；只保留 G5/G16/G23/L* 功能门禁与残余风险 | **RESOLVED** |

---

## 17. Freeze / implementation gate

本 feature 的冻结条件与后续实施条件：

- [x] G1–G30 全部 resolved，本文对应段落改为 locked；
- [x] ADR 0011 accepted；
- [x] `ARCHITECTURE_CONTRACT.md` 升版并同步 D1/D6/D9/D14/D16/G*；
- [x] `docs/ROADMAP.md` 增 P3.3 与 exit gate；
- [x] Poirot module map 最终审阅，COPY/ADAPT/OMIT 范围冻结；
- [x] threat model、network、secret、mount、scope、retention、failure semantics 边界完成 grilling；
- [x] image/SDK/version/security baseline 与 G30 性能非目标边界完成 grilling；
- [x] feature version 去掉 `-draft`；
- [x] 建立 [`P3_3_agent_tool_sandbox.md`](../plans/P3_3_agent_tool_sandbox.md) v0.1.0 implementation plan；
- [x] plan preflight 获取并记录 Pi `main@784653468c42387f607d41ed5ca533100e7eb2fe`，确认 AgentTool execution 仍为 direct call；每个 Pi implementation PR 仍须复核当时 `main`。

---

## 18. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| `0.1.31` | 2026-07-31 | 无边界语义 patch：建立 `P3_3_agent_tool_sandbox.md` v0.1.0 todo，逐文件落实 transplant map、A–F 串行阶段与 O/S/L 双平台 exit gate；记录 Pi `main@7846534` 和 `agent-sandbox==0.0.30` async bash offset-long-poll 源码 preflight；implementation 尚未开始 |
| `0.1.32` | 2026-08-01 | 无边界语义 patch（ADR 0011-A）：arm64 验收 daemon 措辞从字面 "Docker Desktop" 放宽为 arm64 macOS Docker daemon（orbstack 实测接受为 F4 证据）；G18 §9.2.5 与 plan/契约指针同步；Linux amd64 证据仍强制，live skip 仍不能关闭阶段；执行语义/加固/digest/no-fallback 不变 |
| `0.1.30` | 2026-07-31 | 用户接受 ADR 0011 并冻结 feature：G1–G30、Poirot SHA、transplant map、Pi/App ownership、Docker-only universal execution、scope/workspace/lifecycle、RPC、hardening/network/secret/error/rollout/performance 边界正式生效；架构契约 v0.3.7 + Roadmap P3.3 同步；implementation plan 尚未建立，禁止修改运行时代码 |
| `0.1.30-draft` | 2026-07-31 | G30 resolved，G1–G30 grilling completed：Poirot 无 cold/warm、单调用、P50/P95、throughput 或 load benchmark；OMIT 性能 SLA、baseline suite、性能 CI、sandbox latency telemetry/span 与 tuning config；只保留 G5 readiness、G16 真并行、G23 warm reclaim、L1–L5 双平台功能门禁，cold/worker overhead 作为残余风险；feature 仍 draft，待 ADR 0011 + architecture/Roadmap 同步 |
| `0.1.29-draft` | 2026-07-31 | G29 resolved：复制 Poirot/Pi catch-all，全部 execute 期 sandbox acquire/runtime/worker/protocol/serialization/timeout/OOM/container-exit 异常转现有脱敏 error tool result；不强制 task fail；G5 startup fail 与 G15 abort 保持独立；只保留 per-container health check/drop，OMIT fatal taxonomy、provider-wide unhealthy/circuit breaker/sandbox retry controller；G30 继续 open |
| `0.1.28-draft` | 2026-07-31 | G28 resolved：Poirot 只有 `use` 整体禁用与六工具 allowlist bypass，没有 shadow/双跑/百分比/session/tool rollout；二者均不符合 G1/G4 universal fail-closed，全部 OMIT；production 以应用版本一次切换全部 AgentTool，只复用 G5 readiness，回退走既有版本部署回滚；移除 `sandbox.enabled/provider`，不新增 rollout controller/API/state/telemetry；G29–G30 继续 open |
| `0.1.27-draft` | 2026-07-31 | G27 resolved：Pi standalone 保留 upstream-compatible DirectToolExecutor；App offline/unit/integration tests 仅可通过 Python 参数显式 DI Direct 或 test-local protocol mock/spy；OMIT 可发布 FakeToolExecutor、Poirot LocalRuntime/LocalSandboxProvider/LocalSecurityGuard、任意 provider 反射与 direct/local/fake/disabled 配置；USE_FAUX 不改变 executor，正常 dev/production 始终 Docker；G28–G30 继续 open |
| `0.1.26-draft` | 2026-07-31 | G26 resolved：纯 OMIT Poirot `present_files`、SandboxMiddleware artifact branch、ArtifactServer、LocalArtifactStore、artifact state/reducer 与 reporting/multi-agent delivery；不新增 `.poirot/outputs`、文件复制、registry/download route/URL 回写/preview/retention；现有 report JSONL/SOCM/API 不变，未来文件交付另 feature；G27–G30 继续 open |
| `0.1.25-draft` | 2026-07-31 | G25 resolved：只 COPY Poirot `AuditGuard` 与 provider lifecycle logger，Docker 路径不注入 journal，worker fixed command 不携带 RPC payload/secret；Pi events + session JSONL 保持 tool call/result SoT；OMIT LangGraph RunJournalMiddleware/RunJournal/ActivityTracker、新 audit store/API/span 字段、args/result logging 与独立 redaction framework；G26–G30 继续 open |
| `0.1.24-draft` | 2026-07-31 | G24 resolved：复制 Poirot no-change 1800s、idle 600s/scan 60s、replicas 3、readiness 60s/request 5s、stop 15s/inspect 5s；OMIT global hard timeout 与 aggregate workspace quota；仅为 G18 固定 1 CPU/2 GiB/128 PID/每 tmpfs 256 MiB/nofile 1024/fsize 100 MiB，仅为 G13 固定各类 RPC 5 MiB/diagnostic 10,000 bytes；数值不开放 tuning config；G25–G30 继续 open |
| `0.1.23-draft` | 2026-07-31 | G23 resolved：复制/适配 Poirot 三层 acquire、same-ID warm pool、soft replicas、orphan reconciliation、active+warm idle cleanup 与 shutdown；按当前 App 外层 parent Agent run 一次 lazy acquire/finally release，parallel tool/sub-agent 共用；Poirot 不存在且现有串行 run 边界不需要的 per-call lease/refcount OMIT；G24–G30 继续 open |
| `0.1.22-draft` | 2026-07-31 | G22 resolved：host SDK 固定 `agent-sandbox==0.0.30`，AIO base 固定 1.11.0 multi-arch manifest digest，production derived worker 只按 build digest 运行，protocol 固定 `agent-tool-rpc.v1`；复用 G5 startup canary，无 version service/auto-upgrade/fallback；G23–G30 继续 open |
| `0.1.21-draft` | 2026-07-31 | G21 resolved：复制 Poirot container environment 路径，仅按名称继承现有七项 search provider 配置，scope 内受信 tool 共享；不传 LLM/full host env，不挂 `.env`，不做 per-tool channel/secret service/rotation；值不进 Docker argv/worker frame，inspect 可见作为残余风险；G22–G30 继续 open |
| `0.1.20-draft` | 2026-07-31 | G20 resolved + grilling correction：撤回未请求的 per-scope network/egress gateway/provider allowlist/DNS/private/metadata policy，全部 OMIT；复制 Poirot loopback control port + Docker default bridge/egress，不加 host-gateway，明确接受网络残余风险；新增“Poirot 无且用户未要求则 OMIT”硬上限；G21–G30 继续 open |
| `0.1.19-draft` | 2026-07-31 | G19 resolved：production 仅允许 `data/sandboxes/<full-64hex>` → Poirot `/mnt/poirot/user-data` rw fixed bind；root/child canonical + symlink gate；代码 baked-in；Poirot arbitrary `mounts`/`extra_mounts` OMIT，repo/env/db/sessions/home/socket 等其余 host path 全禁；G20–G30 继续 open |
| `0.1.18-draft` | 2026-07-31 | G18 resolved：non-root/read-only rootfs/capped tmpfs/cap-drop/no-new-privileges/effective seccomp/resource limits/loopback control/socket+privileged+host namespace ban 全部 MUST，并以真实 Docker + inspect 验证；AIO 不兼容则回开 G17，不允许降级；具体数值留 G24；G19–G30 继续 open |
| `0.1.17-draft` | 2026-07-31 | G17 resolved：保留 Poirot AIO server/SDK transport，构建 pinned AIO digest 之上的薄派生 multi-arch worker image；代码/依赖 baked-in，不挂 repo、不运行时安装、不另写 sandbox server；版本 tuple 留 G22；G18–G30 继续 open |
| `0.1.16-draft` | 2026-07-31 | G16 resolved：同 parent scope 的 parallel AgentTool 在同一 active container 内以独立 worker process 真并行；Pi 保持 sequential/parallel 与 source-order；Poirot runtime 全局命令锁在 AgentTool 路径 OMIT；G17–G30 继续 open |
| `0.1.15-draft` | 2026-07-31 | G15 resolved：不新增 per-process PID/kill RPC；Pi/App abort 适配到 Poirot scope container destroy，并 bounded verify stopped；workspace 保留；新增“父本不存在且非现有契约必需则 OMIT”总原则；G16–G30 继续 open |
| `0.1.14-draft` | 2026-07-31 | G14 resolved：Poirot 无 partial-update 父本；为保持 Pi parity，worker 发有序 JSON update 后再发唯一 final，host 保持既有 update/late-update 语义；具体 carrier 留 runtime 实测/plan；G15–G30 继续 open |
| `0.1.13-draft` | 2026-07-31 | G13 resolved：Poirot Docker/provider/runtime 之上只新增最小 versioned JSON AgentTool bridge；禁止 pickle/Python object/source/repr fallback，非 JSON fail closed；限额类别锁定、具体数值留 G24，update transport 留 G14；G14–G30 继续 open |
| `0.1.12-draft` | 2026-07-31 | G12 resolved：production v1 拒绝第五参数 ExtensionContext tool，不定义 context RPC/proxy；host handlers 与 standalone Direct parity 保留；新增 G13–G30 每题先查 Poirot frozen code/tests 再推荐的 grilling 规则；G13–G30 继续 open |
| `0.1.11-draft` | 2026-07-31 | G11 resolved：production target 只接受可重新 import 的 module-level async function；closure/lambda/partial/bound/callable object/dynamic/sync 全部启动失败，不 pickle、不静默移除、不 host fallback；G12–G30 继续 open |
| `0.1.10-draft` | 2026-07-31 | G10 resolved：`AgentTool.executionTarget` 携带 provider-neutral runtime metadata，App immutable registry 校验最终 binding；wrapper 保留 target/lineage，RegisteredTool 只供 provenance，LLM schema 不变；G11–G30 继续 open |
| `0.1.9-draft` | 2026-07-31 | G9 resolved：workspace 跟随 parent session 生命周期且无独立 TTL；完成/失败/abort/restart/idle cleanup 保留，resume 复用，显式 task delete 随 session cascade 清理；G10–G30 继续 open |
| `0.1.8-draft` | 2026-07-31 | G8 resolved：ephemeral sub-agent 继承 parent session sandbox scope/workspace，不使用自身 in-memory session id；Agent state/transcript/extension runtime 继续独立；并行与 lease 留 G16/G23；G9–G30 继续 open |
| `0.1.7-draft` | 2026-07-31 | G7 resolved：直接适配 Poirot deterministic SHA-256 recipe，使用 version + `local-default` + parent session 的完整 64 hex；不引入 HMAC；v1 明确 single-tenant，未来 auth 先验 ownership 再注入 tenant identity；G8–G30 继续 open |
| `0.1.6-draft` | 2026-07-31 | G6 resolved：一个 parent session 对应稳定逻辑 sandbox scope/workspace；task/call id 仅作 metadata；不同 session 隔离，物理 container 可重建；G7–G30 继续 open |
| `0.1.5-draft` | 2026-07-31 | G5 resolved：production lifespan 在 `yield` 前完成 Docker/image/worker handshake 与 canary readiness；失败则清理 partial-init 并阻止 App 启动；scope container 仍可 lazy/warm；G6–G30 继续 open |
| `0.1.4-draft` | 2026-07-31 | G4 resolved：production v1 只允许 Docker sandbox provider/runtime；Docker 不可用时禁止降级 LocalRuntime、宿主 subprocess/FS 或 Direct executor；失败时机留 G5；G5–G30 继续 open |
| `0.1.3-draft` | 2026-07-31 | G3 resolved：只隔离通过校验后的 `AgentTool.execute()`；capability import/register/prepare 与 extension handlers 留在可信宿主控制面；加载期恶意/supply-chain package 风险明确移出本 feature；G4–G30 继续 open |
| `0.1.2-draft` | 2026-07-31 | G2 resolved：锁定 Pi engine seam + App sandbox adapter/wiring 双层归属，由 P3.3 统一交付；模块契约可映射时必须优先 COPY，ADAPT/NEW-HOST 均须逐文件举证；G3–G30 继续 open |
| `0.1.1-draft` | 2026-07-31 | G1 resolved：锁定 `competitive_app` production 全部 AgentTool 调用必须显式进入 sandbox 且无宿主 fallback；`pi_agent` 独立 library 保留 upstream-compatible Direct executor 默认值；G2–G30 继续 open |
| `0.1.0-draft` | 2026-07-31 | 基于当前仓库代码、Pi main 调查快照与 Poirot frozen SHA 建立 AgentTool universal sandbox 需求边界草案；记录 FACT、推荐拓扑、transplant map、security/verification gates 与 G1–G30 grilling 队列；未改架构契约/roadmap，禁止实现 |
