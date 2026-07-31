# Plan: P3.3 — Production AgentTool Docker sandbox

| Field | Value |
|-------|-------|
| **plan_id** | `P3.3-agent-tool-sandbox` |
| **plan_version** | `0.1.1` |
| **status** | **active — A–E + F1/F2/F5 done；F3（Linux amd64）/F4（Docker Desktop arm64）证据待外部 host** |
| **created** | 2026-07-31 |
| **updated** | 2026-08-01 |
| **roadmap** | [`docs/ROADMAP.md`](../ROADMAP.md) stage **P3.3** |
| **contract** | [`docs/contracts/ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.7** |
| **feature** | [`docs/features/agent_tool_sandbox_v1.md`](../features/agent_tool_sandbox_v1.md) **v0.1.31 frozen** — G1–G30 |
| **ADR** | [`0011-agent-tool-sandbox-runtime.md`](../contracts/adr/0011-agent-tool-sandbox-runtime.md) **accepted** |
| **depends_on** | **P3.2 done**；P3 local loader；P3.1 extension runtime；现有 P4 session/task/wiring |
| **Pi source** | `earendil-works/pi` `main` @ `784653468c42387f607d41ed5ca533100e7eb2fe`（2026-07-31 preflight；每个 Pi PR 实施前再确认） |
| **sandbox source** | `HezaoHezao/poirot@86bf279ad90c180f0ba696755620dd7d6661465e` |
| **runtime tuple** | `agent-sandbox==0.0.30`；AIO base `sha256:6328d7fd2f0ff0b4c147c3d05b3df1ce331f4a482eb6e550ecd64ed1fcf906e7`；`agent-tool-rpc.v1` |
| **target** | Pi provider-neutral executor seam + App Poirot/Docker adapter/wiring + pinned worker image |
| **tests** | Feature §14 O1–O17、S1–S12、L1–L5；Linux amd64 + Docker Desktop arm64 live evidence |
| **non_goal** | LocalRuntime；tool-name bypass；artifact delivery；remote/K8s/E2B；rollout switch；audit store；egress subsystem；性能 SLA/telemetry/tuning |

---

## 0. Purpose and approach

1. 在 Pi 唯一真实 `AgentTool.execute()` 调用点加入 provider-neutral executor seam，保持当前/upstream 的 validation、extension、event、result 和 JSONL 次序。
2. 在 `competitive_app.adapter.out.sandbox` 按 frozen Poirot SHA 移植 sandbox facade、contracts、Docker backend/runtime/provider、path/guard 与 lifecycle；能映射就 `COPY`，确有 host 差异才 `ADAPT`。
3. 用最小 `NEW-HOST` JSON worker bridge 执行任意已批准、可重新 import 的四参数 module-level async tool；production 全覆盖且无 host/Direct/Local fallback。
4. 用 pinned AIO-derived multi-arch image、FastAPI startup canary、固定 hardening 与真实 Docker gates 关闭阶段。
5. 保持 App 的 JSONL/SOCM/SQLite、task/session、workflow、LLM 和 extension runtime 在宿主控制面；worker 不是第二 Agent runtime。

**实施策略：** 先关闭 Pi direct parity，再做纯协议与 Poirot facade，之后接 Docker lifecycle/image，最后接 App production wiring。不得先在 App startup monkey-wrap 当前工具，也不得复制 Poirot `SANDBOX_TOOL_NAMES` passthrough。

---

## 1. Binding constraints

| Source | Must |
|--------|------|
| Feature v0.1.31 | G1–G30、§3–§15 全部锁定；plan 不重新解释或扩大 |
| ADR 0011 | D-SBX1–D-SBX10；单控制面 + Docker tool 数据面；Pi/App 双层所有权 |
| Architecture D1/D6/D9/D14/D16 | Docker policy 不进 Pi core/Domain；Pi 语义只对齐当时 `main`；P3.3 串行关门 |
| G1/G4/G27/G28 | App production/正常 dev server 只有 Docker；Direct 仅 Pi standalone 默认或 Python 参数显式 test DI |
| G3 | package import/register/prepare/extension handlers 留宿主；只隔离已校验 `execute()` |
| G6–G9/G23 | parent session scope；ephemeral 继承；workspace 独立持久；outer run 一次 lazy acquire/finally release |
| G10–G14/G16 | approved import target；JSON-only RPC；partial update；同 container 独立 worker process 真并行 |
| G15/G24 | abort destroy scope；无 per-process kill API；固定 lifecycle/resource/size 数值；无 global hard timeout |
| G17–G22 | pinned SDK/base/derived digest；唯一 workspace mount；固定七项 env；Poirot network parity；hardening MUST |
| G25/G26/G29/G30 | Pi JSONL SoT；无 artifact/audit store；execute error result parity；无性能产品面 |
| License | 每个 COPY/ADAPT 文件保留 Poirot path/SHA/MIT/host delta；image 保留 Poirot MIT 与 SDK Apache-2.0 notice |

### 1.1 Frozen source preflight

2026-07-31 已重新读取上游代码，而非只看文档：

- Pi `main@784653468c42387f607d41ed5ca533100e7eb2fe` 的 `packages/agent/src/agent-loop.ts:666-700` 仍直接调用 `prepared.tool.execute(...)`，没有 upstream executor seam；P3.3 seam 仍是 ADR 列名的 `NEW-HOST`。
- Poirot `86bf279...` 的 provider 仍是 active → same-ID warm → cross-process discover/create 三层 acquire，outer middleware release 一次；其 `DockerRuntime` 仍有全局同步锁且只返回最终 output，因此 parallel/update 必须按 frozen feature `ADAPT/NEW-HOST`。
- `agent-sandbox==0.0.30` wheel 的 `AsyncSandbox.bash` 已确认提供 `exec(async_mode=True, max_output_length=0)`、`write(...)`、基于 stdout/stderr byte offset 的 `output(wait=True, wait_timeout=...)` 与 `close_session(...)`。

因此 G14 的具体 carrier 在本 plan 锁定为：

```text
fixed worker command (no payload/secret in argv)
  → AsyncSandbox.bash.exec(async_mode=True, max_output_length=0)
  → AsyncSandbox.bash.write(request JSON + newline)
  → AsyncSandbox.bash.output(offsets, wait=True, wait_timeout=5) long-poll
  → newline-delimited update/result/error frames on stdout
  → stderr only as bounded diagnostic
  → close_session after terminal/exit
```

限制：每个 tool call 使用独立 bash session/process；不使用 `bash.kill()` 实现用户 abort，G15 仍统一 destroy scope container；不设置 SDK `hard_timeout`；不得恢复 SDK output truncation或 Poirot runtime 全局锁。

### 1.2 Baseline gate G0

当前 offline suite 需要显式假的 Tavily config 才满足既有 co-load fixture：

```bash
TAVILY_API_KEY=offline-test uv run pytest -m "not live" -q
```

2026-07-31 baseline：`324 passed, 35 deselected`。不提供该测试值时，既有 `test_reasonix_search_coload.py` 会因 Tavily config gate 得到零工具，记录为环境前置而非 P3.3 回归。implementation PR 不得通过修改搜索 feature 语义绕开此 baseline。

---

## 2. Frozen implementation map

分类只允许 `COPY / ADAPT / OMIT / NEW-HOST`。`COPY` 只做包/import/license 机械调整；`ADAPT` 必须在文件头或紧邻测试记录 host delta；不得把可映射父本改写为新的抽象。

### 2.1 Pi executor seam

| Mode | Target | Responsibility / exact delta |
|------|--------|------------------------------|
| `NEW-HOST` | `packages/agent/src/earendil_works/pi_agent/tool_execution.py` | `ToolExecutionTarget`、`AgentToolExecutor` protocol、`DirectToolExecutor`、target derivation/signature helpers；零 Docker/App import |
| `ADAPT` | `packages/agent/src/earendil_works/pi_agent/types.py` | `AgentTool.executionTarget`；`AgentLoopConfig.toolExecutor/toolExecutionScopeId`；LLM schema 不变 |
| `ADAPT` | `packages/agent/src/earendil_works/pi_agent/agent_loop.py` | 唯一 direct call 改为 executor call；before/after/events/catch-all/source-order 不变 |
| `ADAPT` | `packages/agent/src/earendil_works/pi_agent/agent.py` | `AgentOptions` 与 per-run config 传播 executor/scope；standalone 默认 Direct |
| `ADAPT` | `packages/agent/src/earendil_works/pi_agent/harness/agent_harness.py` | constructor 接收 executor + parent scope；session metadata 仍由 Harness/App 绑定 |
| `ADAPT` | `packages/agent/src/earendil_works/pi_agent/extensions/wrapper.py` | wrapper 前推导原 callable target；`functools.wraps` + target/lineage 保留；五参数标记可验证 |
| `ADAPT` | `packages/agent/src/earendil_works/pi_agent/__init__.py` | 仅导出 provider-neutral contract/Direct/target |

Pi seam 的 normative call：

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

`DirectToolExecutor` 必须原样调用 `tool.execute(tool_call_id, params, signal, on_update)`；它不要求 target，忽略 standalone 默认的空字符串 scope，且不捕获或改写异常。App sandbox executor 必须拒绝空 scope。现有 low-level loop catch-all 继续唯一负责 error tool result。

### 2.2 Poirot sandbox infrastructure

所有 source 相对 `poirot/backend/agents/` @ frozen SHA。

| Mode | Poirot source | Target | Required host delta |
|------|----------------|--------|---------------------|
| `COPY` | `sandbox/exceptions.py` | `adapter/out/sandbox/exceptions.py` | import path only；错误层级/details 保留 |
| `ADAPT` | `sandbox/types.py` | `adapter/out/sandbox/types.py` | stdlib UTC；full 64-hex id；固定 config 常量 |
| `COPY` | `sandbox/contracts/path_translator.py` | `adapter/out/sandbox/contracts/path_translator.py` | import path only |
| `COPY` | `sandbox/contracts/security_guard.py` | `adapter/out/sandbox/contracts/security_guard.py` | import path only |
| `ADAPT` | `sandbox/contracts/sandbox_runtime.py` | `adapter/out/sandbox/contracts/sandbox_runtime.py` | async worker frame execution；删除 file facade/PID kill API |
| `ADAPT` | `sandbox/contracts/sandbox_provider.py` | `adapter/out/sandbox/contracts/sandbox_provider.py` | async acquire/release/destroy_scope/shutdown；parent scope input |
| `ADAPT` | `sandbox/contracts/sandbox_backend.py` | `adapter/out/sandbox/contracts/sandbox_backend.py` | CRUD + locked hardening/resource identity；无 arbitrary mounts |
| `ADAPT` | `sandbox/sandbox.py` | `adapter/out/sandbox/sandbox.py` | 保留 validate→translate→execute→mask；仅 worker command path |
| `COPY` | `sandbox/translators/docker_path_translator.py` | `adapter/out/sandbox/translators/docker_path_translator.py` | fixed `/mnt/poirot/user-data` mapping |
| `COPY` | `sandbox/guards/audit_guard.py` | `adapter/out/sandbox/guards/audit_guard.py` | 不注入 journal；fixed command 不含 payload |
| `ADAPT` | `sandbox/guards/docker_path_guard.py` | `adapter/out/sandbox/guards/docker_path_guard.py` | fixed prefix + traversal/symlink/worker path validation |
| `ADAPT` | `sandbox/utils/sandbox_id.py` | `adapter/out/sandbox/utils/sandbox_id.py` | version + `local-default` + parent session；完整 SHA-256 |
| `ADAPT` | `sandbox/docker/executor.py` | `adapter/out/sandbox/docker/executor.py` | Docker CLI only；删除 WSL/Apple Container branches |
| `COPY` | `sandbox/docker/cross_process_lock.py` | `adapter/out/sandbox/docker/cross_process_lock.py` | lock path/key mechanical adaptation |
| `ADAPT` | `sandbox/docker/readiness.py` | `adapter/out/sandbox/docker/readiness.py` | async polling + image/protocol/build/canary identity |
| `ADAPT` | `sandbox/docker/local_container_backend.py` | `adapter/out/sandbox/docker/local_container_backend.py` | digest image、单 mount、loopback port、七项 env、G18/G24 flags；删 `unconfined`/extra mounts |
| `ADAPT` | `sandbox/docker/docker_sandbox_provider.py` | `adapter/out/sandbox/docker/docker_sandbox_provider.py` | 三层 acquire/warm/orphan/idle/shutdown；async/FastAPI；public destroy_scope；无 signal handler/refcount |
| `ADAPT` | `sandbox/runtimes/docker_runtime.py` | `adapter/out/sandbox/runtimes/docker_runtime.py` | `AsyncSandbox.bash` per-call session + offset long-poll；无全局 lock；abort 交 destroy_scope |
| `ADAPT` | `sandbox/integration/config.py` | `adapter/out/sandbox/types.py` + `competitive_app/wiring.py` | 只保留 image digest/workspace root；封闭 Docker provider |
| `ADAPT` | `sandbox/integration/bootstrap_sandbox.py` | `ApplicationState.shutdown()` + FastAPI lifespan | bounded startup rollback/shutdown；不以 atexit 为唯一清理 |

### 2.3 Required host bridge and current-tool compatibility

| Mode | Target | Responsibility |
|------|--------|----------------|
| `NEW-HOST` | `adapter/out/sandbox/protocol.py` | strict `agent-tool-rpc.v1` request/frame codec、sequence/final/JSON/byte limits |
| `NEW-HOST` | `adapter/out/sandbox/approved_registry.py` | host immutable name→module/qualname binding；signature/lineage/collision/image-manifest validation |
| `NEW-HOST` | `adapter/out/sandbox/tool_executor.py` | implement Pi protocol；registry check；runtime frames→on_update/final；never host execute |
| `NEW-HOST` | `adapter/out/sandbox/worker.py` | read one stdin request；check baked manifest；import target；await four-arg execute；emit JSONL frames |
| `ADAPT` | four current tool modules under `capability_packages/{echo_example,search_*}/extensions/` | move `AgentTool`/result-only imports behind register/`TYPE_CHECKING` if required so worker imports execute target without importing Pi control plane；execute function bytes/behavior unchanged |
| `NEW-HOST` | `deploy/tool-sandbox/approved_tools.json` | baked six current tool name/module/qualname bindings；host visible registry must be subset and exact match |
| `NEW-HOST` | `deploy/tool-sandbox/Dockerfile` | pinned AIO base；Python worker + approved code/deps only；multi-arch build |
| `NEW-HOST` | `deploy/tool-sandbox/licenses/` | exact Poirot MIT and `agent-sandbox` Apache-2.0 notices copied into image |

`protocol.py`、registry 与 worker 是 G1/G10/G13/G14 强制的最小 glue，不拥有 Agent loop、LLM、workflow、Session 或 Docker lifecycle。worker image 不安装/复制 FastAPI、App workflow、session runtime 或完整 Pi control plane。

### 2.4 Explicit OMIT

| Poirot / candidate | Status |
|--------------------|--------|
| `identity_translator.py`、`local_path_translator.py`、`local_runtime.py`、`local_sandbox_provider.py`、`local_security_guard.py`、`permissive_guard.py` | `OMIT` |
| `file_operation_lock.py`、`search.py`、Sandbox file façade methods、六个 product tools | `OMIT` |
| `integration/context.py`、`integration/tools.py`、`middlewares/sandbox_middleware.py` | `OMIT` |
| arbitrary provider reflection、`POIROT_SANDBOX_USE`、`SANDBOX_TOOL_NAMES` | `OMIT` |
| arbitrary `mounts/extra_mounts`、repo/config/home/session/db/docker.sock mounts | `OMIT` |
| remote backend/K8s/E2B、multiagent sandbox bridge | `OMIT` |
| `present_files`、ArtifactServer/LocalArtifactStore、report delivery | `OMIT` |
| RunJournal/ActivityTracker、新 sandbox audit DB/API/span/redaction subsystem | `OMIT` |
| per-process PID/kill RPC、lease/refcount、provider-wide circuit breaker/retry controller | `OMIT` |
| egress proxy/network lifecycle/domain allowlist/private/metadata policy | `OMIT` |
| runtime enabled/provider/direct/local/fake/rollout/kill-switch/shadow/dual config | `OMIT` |
| hard timeout、aggregate workspace quota、performance benchmark/SLA/telemetry/tuning | `OMIT` |

### 2.5 Test transplant map

| Mode | Poirot test source | Local test obligation |
|------|--------------------|-----------------------|
| `COPY` | `test_exceptions.py`、protocol ABC tests、`test_docker_path_translator.py`、`test_audit_guard.py`、`test_cross_process_lock.py` | preserve fixtures/assertions except import paths |
| `ADAPT` | `test_sandbox.py` | only worker command validate→translate→execute→mask；file façade cases removed |
| `ADAPT` | `test_docker_path_guard.py`、`test_sandbox_id.py` | fixed prefix/symlink/traversal + full 64-hex recipe |
| `ADAPT` | `test_executor.py` | Docker CLI only；WSL cases removed |
| `ADAPT` | `test_readiness.py` | async handshake/build/protocol/canary and timeout cleanup |
| `ADAPT` | `test_local_container_backend.py` | exact command/inspect hardening、digest、mount/env/network/resource behavior；remove `unconfined` expectations |
| `ADAPT` | `test_docker_sandbox_provider.py` | active/warm/discover/replicas/orphan/idle/release/destroy/shutdown with async scope semantics |
| `ADAPT` | `test_docker_runtime.py` | async bash session/write/output offsets/frames/close；parallel overlap；no global lock/file façade |
| `ADAPT` | `test_bootstrap_sandbox.py`、`test_config.py` | FastAPI/ApplicationState lifecycle；closed config surface |
| `OMIT` | Local/permissive/file/search/tool/middleware/artifact/remote/multiagent tests | omitted production surfaces must instead have absence/contract assertions |

---

## 3. Target layout

```text
packages/agent/src/earendil_works/pi_agent/
  tool_execution.py
  types.py                         # modify
  agent_loop.py                    # modify: one invocation seam
  agent.py                         # modify: executor/scope propagation
  harness/agent_harness.py         # modify
  extensions/wrapper.py            # modify: target/lineage
  __init__.py                      # modify exports

competitive_app/src/competitive_app/
  adapter/out/sandbox/
    __init__.py
    exceptions.py
    types.py
    sandbox.py
    protocol.py
    approved_registry.py
    tool_executor.py
    worker.py
    contracts/
      __init__.py
      path_translator.py
      security_guard.py
      sandbox_runtime.py
      sandbox_provider.py
      sandbox_backend.py
    translators/
      __init__.py
      docker_path_translator.py
    guards/
      __init__.py
      audit_guard.py
      docker_path_guard.py
    utils/
      __init__.py
      sandbox_id.py
    docker/
      __init__.py
      executor.py
      cross_process_lock.py
      readiness.py
      local_container_backend.py
      docker_sandbox_provider.py
    runtimes/
      __init__.py
      docker_runtime.py

  wiring.py                       # modify config/composition/readiness/shutdown
  application/workflow/
    session_service.py            # independent session outer scope
    task_service.py               # task run/delete/abort scope lifecycle
    research_runner.py            # parent task scope wraps main + ephemeral
    runtime_registry.py           # abort/shutdown ordering

deploy/tool-sandbox/
  Dockerfile
  approved_tools.json
  licenses/

config/settings.example.yaml      # image digest + workspace root only
competitive_app/pyproject.toml    # agent-sandbox==0.0.30
uv.lock

tests/packages/agent/
  unit/test_tool_execution.py
  integration/faux/test_tool_executor_seam.py
  contract/test_deps.py

tests/competitive_app/
  contract/test_sandbox_contract.py
  unit/sandbox/
  integration/test_sandbox_wiring.py
  integration/test_sandbox_scope_lifecycle.py
  integration/live/test_live_agent_tool_sandbox.py
  integration/live/test_live_agent_tool_sandbox_security.py
```

No new HTTP route, SQLite table, JSONL entry type, SOCM schema, CLI or user-facing sandbox API is added.

---

## 4. Status board

Status: `todo` | `in_progress` | `done` | `blocked`.

| Step | Phase | Status | Contract mapping |
|------|-------|--------|------------------|
| G0 | Current Pi/Poirot/SDK code preflight + offline baseline | **done** | Pi `7846534` direct call；Poirot frozen；SDK carrier confirmed；324 offline green with dummy Tavily config |
| A1 | `ToolExecutionTarget` + derivation/signature validation | **done** | G10–G12 / O4 / O17；`test_tool_execution.py` |
| A2 | `AgentToolExecutor` + Direct parity | **done** | G1/G2 / O2；`test_tool_execution.py::test_direct_executor_*` |
| A3 | low-level loop seam + Agent/Harness propagation | **done** | G1/G3 / O1/O3；`test_executor_seam.py` / `test_executor_propagation.py` |
| A4 | wrapper lineage + Pi contract/dependency tests | **done** | G10 / O4/O14；wrapper remap + lineage 测试 |
| B1 | strict JSON request/frame codec | **done** | G13/G14/G24 / O5；`test_protocol.py`（5 项） |
| B2 | approved registry + baked manifest contract | **done** | G10/G11/G22 / O4/S7；`test_approved_registry.py` |
| B3 | one-request worker + update/final/error behavior | **done** | G11–G14/G29 / O5/O8/O17；`test_worker.py` |
| B4 | current six tool targets worker-importable with no control plane | **done** | G11/G17；`test_sandbox_contract.py::test_worker_targets_import_without_pi_control_plane` |
| C1 | COPY pure exceptions/contracts/translator/audit/lock | **done** | G2/G19/G25/O15；17 个 COPY/ADAPT 文件全部带 SHA/MIT |
| C2 | ADAPT facade/types/runtime/provider/backend contracts | **done** | G2/G15/G23 |
| C3 | scope id + workspace/path/symlink guards | **done** | G7/G9/G19 / S1–S4/S12；`test_facade.py` + live S2/S4 |
| C4 | Poirot-derived unit parity/omit tests | **done** | O14/O15；omit 文件不存在断言 |
| D1 | Docker CLI/backend with pinned image + fixed hardening | **done** | G17–G22/G24 / S3/S7/S8/S10/S11；`test_backend.py`（24 项）+ live S3/S10 |
| D2 | async SDK runtime using bash offset long-poll | **done** | G13/G14/G16 / O5/O6 |
| D3 | provider acquire/warm/orphan/idle/destroy/shutdown | **done** | G15/G23/G24 / O7/O10/O11；`test_docker_provider.py`（10 项） |
| D4 | derived multi-arch image + notices + manifest/SBOM/provenance | **done** | G17/G22 / O15/S7；dev-3 digest `sha256:16a07d29…`（provenance=前序 digest，见 §5 决策） |
| D5 | real image readiness/worker/hardening smoke | **done** | G5/G18 / O13/S1–S12；orbstack arm64 真实冒烟全绿 |
| E1 | App config + immutable registry + eager startup composition | **done** | G1/G4/G5/G27/G28 / O4/O13；`test_composition.py` wiring fail-closed 5 项 |
| E2 | main/dynamic/resume/ephemeral scope propagation | **done** | G1/G6/G8 / O1/O9；`_HarnessFactory` parent-derived scope |
| E3 | outer-run lazy acquire + once-only release | **done** | G16/G23 / O6/O10；`test_composition.py` executor/lifecycle 8 项 |
| E4 | abort/shutdown/task-delete/workspace retention | **done** | G9/G15/G23 / O7/O11/S9；live S9 + 真实 Docker task delete smoke |
| E5 | production no-fallback/no-config-bypass contract tests | **done** | G1/G4/G27/G28 / O8/O14/S6；doubles-pair 校验 + 无 env/CLI bypass |
| F1 | full Offline O1–O17 | **done** | feature §14.1；全仓 `-m "not live"` 406 passed |
| F2 | full Security S1–S12 on real Docker | **done** | feature §14.2；`test_live_sandbox_security.py` 12/12（orbstack arm64） |
| F3 | Linux amd64 L1–L5 evidence | blocked | feature §14.3；需外部 Linux amd64 host（见证据表） |
| F4 | Docker Desktop arm64 L1–L5 evidence | blocked | feature §14.3；本机 orbstack（非 Docker Desktop），证据记录见证据表 |
| F5 | full regression/CodeGraph/license/transplant audit | **done** | O12/O14–O16；406 offline + CodeGraph impact/affected + 17 COPY/ADAPT 审计 |
| F6 | plan completed + Roadmap P3.3 done | in_progress | exit gate；待 F3/F4 外部证据后翻转 |

Rules:

- A2/A3 must close Direct parity before App/Docker code can rely on the seam.
- D1–D3 may use mocks until D4 exists, but E1 production composition cannot be declared ready before D5 real canary.
- E2/E3 must be one change set: propagating scope without the outer lifecycle, or lifecycle without universal propagation, is not a valid intermediate production path.
- Ordinary CI may skip F2–F4 only by `live` marker; a skip never changes their status to done.
- P3.3 stays `todo` until F1–F5 all green on both required platforms. Pi-only or App-only delivery does not close the stage.

---

## 5. Phased implementation

### Phase A — Pi provider-neutral seam

**A1. Target metadata**

1. Add frozen `ToolExecutionTarget(module, qualname)` and optional `AgentTool.executionTarget` without changing `to_llm_tool()`.
2. Derive through explicit `__wrapped__` lineage only; require module-level async callable; detect `<locals>`/lambda/partial/bound/callable object/sync/fifth context parameter.
3. `wrap_registered_tool()` calls `functools.wraps`, preserves target and existing execution mode/prepare semantics.
4. Production rejection belongs to App registry validation; Pi standalone may keep `executionTarget=None`.

**A2. Executor and loop**

1. Add `AgentToolExecutor` protocol and singleton/stateless `DirectToolExecutor`.
2. Replace only `_execute_prepared_tool_call()` direct invocation; keep loop catch-all and update drain behavior unchanged.
3. Propagate executor/scope through `AgentLoopConfig`, `AgentOptions`, `Agent`, and `AgentHarness`；standalone scope 默认 `""`，只允许 Direct 忽略该值。
4. No Docker/SDK/App imports, no schema revalidation, no extension dispatch inside executor.

**A3. Tests**

- Spy executor covers sequential/parallel, dynamic state tools, Harness, resume and extension wrapper.
- Direct parity covers final result, raised exception, ordered updates, late update ignore, `terminate` and `addedToolNames`.
- Event trace asserts prepare/validation/before/tool_call/start/update/end/after/tool_result/JSONL order is unchanged.
- Contract tests assert Pi dependency direction and absence of Docker symbols.

### Phase B — Approved target and RPC worker

**B1. Strict protocol**

- Encode/decode with UTF-8 JSON, `allow_nan=False`, string keys only, duplicate-key rejection and exact protocol/call/scope identity.
- Frame sequence 在本 plan 固定从 `1` 开始、每帧加一，允许任意数量 update 和恰好一个 result/error final。
- Enforce 5 MiB request, each frame, cumulative updates and final independently; diagnostic budget 10,000 bytes.
- Reject unknown fields where they could change execution identity; never coerce bytes/object/`repr()`.

**B2. Registry**

- Build immutable registry after capability loading from final visible tool bindings.
- Reject missing/duplicate/collision/non-importable/context-aware targets before readiness.
- Compare host registry against image handshake/baked `approved_tools.json`; runtime subsets may shrink visibility but may not add/rebind targets.
- The model/request supplies no target; executor copies it from approved host metadata.

**B3. Worker**

- Fixed module entrypoint reads exactly one request line from stdin and emits only protocol frames to stdout.
- Re-check target against baked manifest, import with `importlib`, require top-level coroutine function, call four arguments with a worker-local abort signal and frame callback.
- Map uncaught errors to stable safe error codes/messages; provider secrets, traceback, paths and raw repr do not enter frames.
- Close after terminal. Additional input, duplicate final or background late update cannot create a second execution.

**B4. Current tool modules**

- Keep six execute functions and provider behavior unchanged.
- Mechanically defer host-only `AgentTool` type imports so importing the target in the image does not import Agent/LLM/session/workflow control-plane modules.
- Add import-closure test for every baked target before building the image.

### Phase C — Poirot facade/contracts/path/guard transplant

**C1. COPY set**

Copy exceptions, path/security contracts, Docker translator, AuditGuard and cross-process lock first. Preserve symbol names, docstrings/control flow and parent tests; only package imports/license headers change.

**C2. ADAPT set**

- Narrow `SandboxRuntime` to worker execution frames and `Sandbox` to the fixed worker command chain.
- Make provider/backend contracts async and scope-based; add only `destroy_scope()` required by G15.
- Keep error hierarchy and validate→translate→execute→mask ordering.

**C3. Scope/workspace**

- Derive exact 64-hex id from feature G7; never accept raw HTTP/tool scope input.
- Canonicalize root once at startup; child must be a non-symlink direct `<64hex>` directory.
- Fixed container path remains `/mnt/poirot/user-data`; no arbitrary mount API exists.

### Phase D — Docker backend/runtime/provider/image

**D1. Backend**

Assemble Docker CLI args from locked constants only:

```text
image: digest required
mount: <canonical-root>/<scope>:/mnt/poirot/user-data:rw (only bind)
port: AIO control bound to 127.0.0.1
user: numeric non-root
rootfs: read-only
tmpfs: required paths, each 256 MiB
cap-drop=ALL; no-new-privileges; effective seccomp (never unconfined)
cpus=1; memory=memory-swap=2 GiB; pids=128
nofile=1024; fsize=100 MiB
network: Docker default bridge; never host network/host-gateway
env: only the seven G21 names via --env NAME
```

Create/discover/destroy/inspect must reject non-digest images, invalid scope/container names, unexpected mounts/privilege/namespace settings and stopped-verification failure.

**D2. Runtime carrier**

1. Start one fixed worker command per tool call with `bash.exec(async_mode=True, max_output_length=0)`.
2. Send request only through `bash.write`; no request/secret in command/argv.
3. Long-poll `bash.output` with returned byte offsets and `wait_timeout=5`; incremental buffer parses complete JSON lines and enforces byte budgets before decode.
4. Deliver updates synchronously in sequence before accepting final; stderr is diagnostic only.
5. Close session in `finally`; do not serialize parallel calls with a runtime-global lock.
6. User abort marks scope closed to new work and calls provider `destroy_scope()`; do not use SDK `kill` as the product abort contract.

**D3. Provider lifecycle**

Port Poirot active/same-ID-warm/discover-create, soft replicas=3, cross-process lock, orphan reconciliation, idle=600s/scan=60s, no-change=1800s, readiness=60s/request=5s, stop=15s/inspect=5s. Keep cancel-safe create, unhealthy drop and double-discover destroy guard. Remove exclusive signal handlers and all per-call release/refcount behavior.

**D4. Image**

- `FROM ghcr.io/agent-infra/sandbox@sha256:6328...906e7`.
- Bake worker, approved manifest, four current tool modules and exact provider dependencies; disable unused AIO services required to satisfy G18.
- No runtime install, source mount, FastAPI, LLM provider, Agent loop, Session or workflow code.
- Build amd64/arm64 manifest, emit derived digest/SBOM/provenance, and copy license notices into image.
- Production config records only the resulting derived digest; Dockerfile base digest is not a valid runtime substitute.

### Phase E — App composition and lifecycle

**E1. Startup order**

1. Load/validate App config: `sandbox.image` digest and canonical `sandbox.root` only; no enabled/provider/tuning fields.
2. Load capability packages on host, construct/validate immutable registry, then construct Docker backend/provider/runtime/executor.
3. Before FastAPI lifespan `yield`, verify daemon, image identity, protocol/build/manifest handshake and isolated echo canary.
4. Any failure unwinds canary/container/provider/client and already-open App resources before re-raising; no degraded state.
5. Pin `agent-sandbox==0.0.30` in `competitive_app/pyproject.toml` and `uv.lock`.

**E2. Universal scope propagation**

- `_HarnessFactory.build()` derives scope only after reading confirmed parent session metadata and injects executor/scope.
- HTTP session prompt and task/resume paths use the same factory.
- `build_ephemeral(..., session_id=parent)` injects the same parent-derived scope; it ignores its `InMemorySessionRepo` id.
- Dynamic `agent.state.tools` subsets carry target metadata; no re-wrapping or name bypass.

**E3. Outer run lifecycle**

- Independent `SessionService.prompt()` wraps one complete locked prompt run.
- Research `TaskService`/`ResearchRunner.run()` wraps the full parent task run so CoverageEngine parallel ephemeral agents share the active scope.
- First execute lazily acquires; outer `finally` releases once. Tool calls/sub-agents never release independently.
- Runs with no tool call create no container.

**E4. Abort/delete/shutdown**

- Session/task abort first rejects new scope calls, then destroys+verifies container and preserves workspace.
- `DELETE /tasks/{id}` aborts/destroys first, then deletes only the derived workspace as part of existing session/JSONL/SOCM/index cascade.
- completed/failed/aborted, idle cleanup, App restart and normal shutdown retain workspace.
- `ApplicationState.shutdown()` order: stop product runs → destroy active/warm containers → close SDK clients → close stores.

**E5. Test DI**

`build_application_state`/factory may accept explicit Python-only executor and lifecycle doubles for tests. Default/omitted arguments always build Docker. No env/YAML/CLI direct/fake/local/disabled setting exists; `USE_FAUX` changes only LLM provider. Test doubles live in test files; no publishable `FakeToolExecutor` is added.

### Phase F — Verification and closeout

**F1. Offline**

```bash
TAVILY_API_KEY=offline-test uv run pytest \
  tests/packages/agent \
  tests/capability_loader \
  tests/competitive_app -m "not live" -q

TAVILY_API_KEY=offline-test uv run pytest -m "not live" -q
```

Map every feature O1–O17 to at least one named test. O15 scans every COPY/ADAPT source header and both license texts; O16 runs CodeGraph impact/affected plus full offline suite.

**F2. Security/live**

Real Docker tests must exercise enforcement, not only command strings: outside-host canary, cross-scope workspace, mount inspect, traversal/symlink, secret absence, no fallback side effect, digest/protocol mismatch, CPU/memory/PID/tmpfs/fsize/RPC/no-change limits, abort/orphan, non-root/caps/seccomp/rootfs, loopback/default egress and stable full scope id.

**F3. Product live**

- L1 readiness + echo container identity + host callable spy.
- L2 all five search/fetch tools through the derived image with real providers.
- L3 full research workflow with parallel ephemeral agents sharing scope.
- L4 real overlap/update/abort/no-change/container-crash behavior.
- L5 terminal states/restart/resume/warm reclaim/task delete/shutdown retention.


Evidence table (2026-08-01; orbstack = arm64 Docker daemon on macOS, NOT Docker Desktop):

| Platform | Image digest | O | S | L1–L5 | Date / sanitized evidence |
|----------|--------------|---|---|-------|---------------------------|
| Linux amd64 | pending（dev-3 为 arm64 构建） | pending | pending | pending | 需外部 Linux amd64 host；测试均为 `live` 标记，主机就绪后直接运行 |
| Docker Desktop arm64 | pending | pending | pending | pending | 本机为 orbstack daemon；`docker info` 含 orbstack 标识；L1 等价验证已由 `test_live_sandbox_security.py`（12/12）+ production e2e smoke 完成 |
| orbstack arm64（本机，参考证据） | `sha256:16a07d2927a6daa024a199e41ab0c29b7812d40198a3a636a3262594f61f8276` | 406 offline + 本仓 O 映射 | S1–S12 12/12 | L1 通过（canary/manifest/production e2e）；L2–L5 需真实 provider key | 2026-08-01：real-Docker production e2e、abort→destroy、task delete→delete_workspace、S1–S12 全绿；无遗留 container（`docker ps -a --filter label=…` 为空） |

**P3.3 已记录决策（本计划增量）：**

1. **buildIdentity 语义 = provenance，非最终 digest**。内容寻址镜像中 manifest `buildIdentity == 最终 digest` 无固定点（D = f(B) 且要求 D == B 与 config digest 同时成立）。因此 baked manifest 的 `buildIdentity` 记录前一构建 digest（dev-3 中为 dev-2 `sha256:90e12a…`），S7 强制链改为：生产只接受 digest pin + `verify_image_identity`（daemon 解析）+ host registry ⊆ baked manifest 逐 target 校验 + canary（worker 侧自行校验 protocol/版本/baked manifest）。
2. **启动握手**：默认 readiness（HTTP 200 + ready state，`/v1/sandbox` 只返回 base env blob，无 protocol/buildIdentity 字段）；manifest handshake 走 `read_baked_manifest`（`docker run --rm --read-only --network none --entrypoint cat`）+ `registry.validate_baked_manifest`；canary 用独立 `CANARY_SESSION_ID` scope，失败即销毁。
3. **模块重映射 host delta（`extensions/wrapper.py::_remap_generated_module`）**：除把 target 从 `pi_extension_<hash>` 重映射到 `capability_packages.*` 外，还把生成的 module 对象注册进 `sys.modules[real_name]`，使 host 侧 lineage 校验（`__code__` 同一文件证明）在 pytest/打包安装（cwd 不在 sys.path）下仍然成立；worker 镜像内仍按真实路径 fresh import。
4. **E5 无 bypass**：`build_application_state` 的 doubles 必须成对传入，缺一即 ValueError（在开任何资源之前校验）；sandbox 组合失败时先 `provider.shutdown()` 并关闭已开的 SQLite stores 再 re-raise（E1.4 unwind）。

Test duration may be recorded diagnostically but is never a pass/fail SLA. Live skip cannot close P3.3.

---

## 6. Serial delivery slices

| Slice | Scope | Merge gate |
|-------|-------|------------|
| PR1 | Phase A Pi seam/Direct parity/target lineage | packages/agent tests + current full offline green；zero Docker/App import in Pi |
| PR2 | Phase B + Phase C protocol/worker/Poirot pure facade and tests | strict RPC/registry + transplant/license audit；no production wiring yet |
| PR3 | Phase D backend/runtime/provider/image | mock parity + real derived-image readiness/security smoke on one platform |
| PR4 | Phase E App production composition/scope/lifecycle | universal/no-fallback contract + App offline integration green |
| PR5 | Phase F both-platform live/security/full regression closeout | O1–O17 + S1–S12 + L1–L5 all green；Roadmap update |

Every PR must refresh the Pi `main` SHA relevant to touched Pi files, run `codegraph callers/impact` before exported-symbol changes, run `codegraph sync` after new source files, and update this status board immediately rather than at final close only.

No slice may ship a production path that silently uses Direct. Before PR4, the new Docker path is not wired as production; at PR4 it becomes the only production path in that application version.

---

## 7. Exit checklist

- [ ] Pi Direct executor matches current upstream direct call and all executor/scope callsites are covered.
- [ ] Main, dynamic, extension, Harness, resume and ephemeral tools all use one injected executor seam.
- [ ] Production registry rejects missing/rebound/non-importable/context-aware targets before startup.
- [ ] Poirot COPY/ADAPT files and tests retain frozen source/SHA/license/host delta.
- [ ] Worker uses fixed command + stdin + offset long-poll JSON frames; no payload/secret in argv/log.
- [ ] Same-scope parallel calls overlap in separate worker processes; sequential remains serial/source-ordered.
- [ ] Abort destroys/verifies the whole scope container; no host/Direct/Local fallback exists.
- [ ] Scope/workspace identity, retention, task delete, warm/orphan/idle/shutdown match G6–G9/G23.
- [ ] Derived digest image satisfies G17–G22/G24 and contains no App/Pi control plane.
- [ ] `agent-sandbox==0.0.30` and both license notices are locked.
- [ ] O1–O17, S1–S12 and L1–L5 are green on Linux amd64 and Docker Desktop arm64.
- [ ] Full offline regression, CodeGraph impact/affected and contract-drift suites are green.
- [ ] Plan status is `completed` and Roadmap marks `P3.3=done`; only then resume AgentTool-dependent P4 expansion.

---

## 8. Revision history

| Version | Date | Change |
|---------|------|--------|
| `0.1.0` | 2026-07-31 | Initial implementation plan from frozen feature v0.1.31/ADR 0011：records Pi `main@7846534` preflight, exact Poirot COPY/ADAPT/OMIT/NEW-HOST map, SDK bash offset-long-poll carrier, A–F serial phases, O/S/L close gates and two-platform evidence table；implementation not started |
| `0.1.1` | 2026-08-01 | **A–E + F1/F2/F5 完成**：status board 全量翻转（G0–F5）；real-Docker production e2e/abort/task-delete smoke 与 S1–S12 12/12 记录；E-phase offline contract tests（`test_composition.py` 19 项 + `test_docker_provider.py` 10 项 + `test_backend.py` 24 项）与 live `test_live_sandbox_security.py`；全仓 offline 406 passed；记录 buildIdentity=provenance 决策、启动握手、`_remap_generated_module` sys.modules host delta、E5 doubles-pair/unwind；F3/F4 双平台证据仍待外部 host |
