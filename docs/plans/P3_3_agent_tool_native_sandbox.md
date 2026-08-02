# Plan: P3.3 — Native AgentTool sandbox

| Field | Value |
|-------|-------|
| **plan_id** | `P3.3-agent-tool-native-sandbox` |
| **plan_version** | `0.1.1` |
| **status** | **active — G0 complete；A–F/V1–V4 not started** |
| **created** | 2026-08-02 |
| **updated** | 2026-08-02 |
| **roadmap** | [`docs/ROADMAP.md`](../ROADMAP.md) stage P3.3 |
| **contract** | [`ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) v0.3.9 |
| **ADR** | [`0012-native-agent-tool-sandbox-runtime.md`](../contracts/adr/0012-native-agent-tool-sandbox-runtime.md) accepted |
| **feature** | [`agent_tool_native_sandbox_v1.md`](../features/agent_tool_native_sandbox_v1.md) frozen v0.2.1 |
| **supersedes plan** | [`P3_3_agent_tool_sandbox.md`](P3_3_agent_tool_sandbox.md) v0.1.2（historical Docker plan） |
| **sources** | `pi-sandbox@0.4.2` + SRT `0.0.67` + `pi-auto-review@0.3.2` |
| **G0 map** | [`P3_3_native_sandbox_G0_map.md`](P3_3_native_sandbox_G0_map.md) v0.1.0 frozen/complete |

## 0. Purpose

用 Python 等价翻译 frozen erichll/SRT/auto-review 源码，将当前 Docker AgentTool 数据面替换为 Linux bubblewrap/seccomp 与 macOS Seatbelt native sandbox。保留已经完成的 provider-neutral executor、approved registry、JSON RPC worker、scope/workspace 和 universal/no-fallback contract。

实施原则：在当前 Pi/App/DDD 所有权下应抄尽抄。能映射时保持职责、输入输出、控制流和失败语义；只为 Python async、当前 executor/RPC、显式 DI 和无 TUI host 差异做 ADAPT。

## 1. Binding constraints

- production native-only；无 Docker/Host IPC/Direct/Local fallback；
- Linux 与 macOS 都是正式 gate；
- `packages/agent` 不新增 native/SRT/approval policy；
- App adapter 拥有 OS/process/filesystem/network IO；Domain 无 IO；
- 每次调用独立 broker/SRT manager；同 scope 并行不加全局锁；
- network 默认 deny，exact one-shot approval grant；
- worker 仅七项 provider env，不继承 full Host env；
- no cgroup/macOS monitor；保留 timeout/process-tree cleanup 和 RPC size limits；
- 每个 COPY/ADAPT 记录 frozen source/version/path/license/host delta。

## 2. Frozen implementation map

The complete per-file source/test/removal classification, artifact integrity, helper hashes, CodeGraph evidence, test IDs, commands, prerequisites, and baselines are binding in [`P3_3_native_sandbox_G0_map.md`](P3_3_native_sandbox_G0_map.md). The tables below are the execution summary and may not broaden or contradict that map.

### 2.1 Keep from current P3.3

| Mode | Target | Responsibility |
|------|--------|----------------|
| KEEP | `packages/agent/.../tool_execution.py` and propagation callsites | provider-neutral executor/Direct/target/scope |
| KEEP | `approved_registry.py` | Host trusted target binding |
| KEEP | `protocol.py` | strict `agent-tool-rpc.v1` codec/limits |
| ADAPT | `worker.py` | native trusted manifest/tool bundle path; execution semantics unchanged |
| ADAPT | `sandbox_tool_executor.py` | propagate signal and bind active native invocation |
| ADAPT | `lifecycle.py` | native readiness/active broker abort/workspace delete/shutdown |
| KEEP/ADAPT | `utils/sandbox_id.py` | parent-session stable scope identity |

### 2.2 Port `pi-sandbox@0.4.2`

| Upstream | Target | Mode |
|----------|--------|------|
| `src/runner.ts` | `native/runner.py` | ADAPT asyncio subprocess/process group/IPC |
| `src/srt-broker.mjs` | `native/broker.py` | ADAPT Python process + current worker invocation |
| `src/policy.ts` | `native/policy.py` | ADAPT Python/tool bundle roots |
| `src/config.ts` | `native/config.py` | COPY-semantics strict parser |
| `src/network-policy.mjs` | `native/network_policy.py` | COPY-semantics |
| `src/approval.ts` | `native/approval.py` | ADAPT explicit Python broker DI |
| `src/traps.ts` | `native/traps.py` | COPY-semantics |
| `src/index.ts` | — | OMIT; existing universal executor owns integration |
| `src/subagent.ts` | — | OMIT; existing ephemeral orchestration inherits scope |
| `src/host-ipc.ts` | — | OMIT; violates no-host-fallback |

### 2.3 Port required SRT `0.0.67`

```text
native/srt/
  manager.py
  policy.py
  linux.py
  macos.py
  seccomp.py
  proxy.py
  process.py
```

Only port code reached by erichll initialize/wrap/cleanup/reset on Linux/macOS. Vendor or reproducibly build the frozen `apply-seccomp` helper for supported architectures; helper identity and license must be verified at startup/build time.

### 2.4 Port required `pi-auto-review@0.3.2`

| Upstream | Responsibility | Mode |
|----------|----------------|------|
| `broker/types.ts` | generic contract in `packages/agent`; concrete types in local capability | COPY-semantics |
| `broker/broker.ts` | hard deny -> reviewer -> grant | ADAPT |
| `broker/grants.ts` | stable hash/TTL/single use | COPY-semantics |
| `broker/circuit-breaker.ts` | denial breaker | COPY-semantics |
| `broker/service.ts` | `packages/agent` generic extension service publication + explicit App DI | ADAPT |
| `integrations/sandbox.ts` | App sandbox trap conversion | COPY-semantics |
| `policy.ts` | local capability strict decision/evidence/redaction | ADAPT Pi Python messages |
| reviewer core in `index.ts` | local capability trusted config/model call/failure mode | ADAPT current model registry |
| TUI feedback/auto-confirm | — | OMIT until a real host UI contract exists |

## 3. Target layout

```text
competitive_app/src/competitive_app/adapter/out/sandbox/
  native/
    __init__.py
    config.py
    policy.py
    traps.py
    network_policy.py
    approval.py
    runner.py
    broker.py
    native_runtime.py
    native_sandbox_provider.py
    srt/
      manager.py
      policy.py
      linux.py
      macos.py
      seccomp.py
      proxy.py
      process.py
  approval/                                  # App trap adapter only
    sandbox.py

packages/agent/src/earendil_works/pi_agent/
  boundary_approval.py                       # generic service contract

capability_packages/pi_auto_review/
  package.json
  config.json                                # package-shipped defaults (COPY src/config.json)
  pi_auto_review/                            # importable subpackage (established local boundary:
    __init__.py                              #   loader imports one entry .py; siblings must be
    types.py                                 #   reachable by import, so they live in a package
    grants.py                                #   under the capability root; see G0 map §3.1)
    circuit_breaker.py
    broker.py
    policy.py
    reviewer.py                              # trusted config + model reviewer core (index.ts split)
  extensions/
    register.py                              # NEW-HOST entry: sys.path bootstrap + register(pi)
```

Exact filenames may only change to match an established local module boundary; any change must update this map before implementation.

## 4. Phases and status

| Phase | Work | Status |
|-------|------|--------|
| G0 | frozen source/license/baseline capture | **done — G0 map v0.1.0** |
| A | Python auto-review types/grants/hard-deny/circuit/evidence core | **done — PR1 gate passed (O6–O10 + trust config; offline 532 passed)** |
| B | Python SRT config/policy/Linux/macOS/seccomp/proxy port | todo |
| C | erichll runner/broker/network approval port | todo |
| D | NativeProvider/Runtime + current worker/registry/RPC integration | todo |
| E | App wiring/readiness/scope lifecycle + Linux/macOS config | todo |
| F | remove Docker production code/dependencies/image/config | todo |
| V1 | offline contract/unit/parity tests | todo |
| V2 | Linux amd64 real enforcement/e2e | todo |
| V3 | arm64 macOS real enforcement/e2e | todo |
| V4 | baseline/resource/license/CodeGraph audit and closeout | todo |

## 5. Verification gates

### 5.1 Offline

- strict config/unknown key/failureMode deny;
- policy and network normalization parity fixtures transplanted from upstream;
- boundary request stable hash, TTL, one-use grant and breaker parity;
- registry/manifest/RPC/partial update behavior unchanged;
- universal executor coverage for main/dynamic/extension/resume/ephemeral;
- no imports from `packages/agent|ai` to App/native modules;
- Domain import/IO guard green;
- no Docker/agent-sandbox production composition remains.

### 5.2 Linux real

- bubblewrap mount/network/PID namespace and nested seccomp active;
- workspace allow; home/App/session/DB/other scope deny;
- network default deny, public exact grant allow, private/mixed DNS deny;
- parallel calls overlap with independent brokers;
- timeout/abort/scope abort leave no process/proxy orphan.

### 5.3 macOS real

- Seatbelt profile active with equivalent filesystem/network decisions;
- same approval, parallel, timeout, abort and cleanup behavior;
- no unsupported-path Host fallback.

### 5.4 Comparison and removal

Record cold/steady/10-way parallel/idle RSS+PIDs/disk against the frozen Docker baseline. No artificial latency SLA. P3.3 closes only after Docker provider/backend/runtime/image/SDK/config are removed and dependency/license audits are green.

## 6. Serial delivery slices

| Slice | Scope | Gate |
|-------|-------|------|
| PR1 | G0 + A approval core | transplanted approval tests + license map |
| PR2 | B SRT platform core | offline argv/profile/policy parity tests |
| PR3 | C + D runner/provider/RPC integration | protocol, abort, parallel, fail-closed tests |
| PR4 | E wiring/readiness + real Linux/macOS gates | both-platform e2e green |
| PR5 | F removal + V4 closeout | no production Docker refs/deps; full regression green |

No slice may wire a partial native sandbox that can fall back to Host or Docker. Production wiring switches only when its required platform readiness tests are present; the final merge removes Docker completely.

## 7. Exit checklist

- [ ] Frozen source archives/SHAs/package versions/licenses recorded.
- [ ] COPY/ADAPT/OMIT map matches actual files and host deltas.
- [ ] Python approval core matches exact grant/hard-deny/failure-mode semantics.
- [ ] Linux and macOS SRT paths pass real enforcement gates.
- [ ] Universal AgentTool execution, RPC, registry, scope/workspace remain green.
- [ ] Abort/timeout/parallel leave no orphan.
- [ ] Worker environment remains the seven-item allowlist.
- [ ] Docker provider/backend/runtime/image/SDK/config removed; no fallback.
- [ ] Full offline suite, contract drift, import boundaries and CodeGraph audit green.
- [ ] Roadmap P3.3 marked done only after every item above is checked.

## 8. Revision history

| Version | Date | Change |
|---------|------|--------|
| `0.1.0` | 2026-08-02 | Initial active plan from ADR 0012 / native feature v0.2.0; preserves current executor/RPC/scope, ports three frozen upstreams, replaces and removes Docker, and defines Linux/macOS real gates |
| `0.1.1` | 2026-08-02 | G0 complete：pins Git/npm integrity/licenses；full pi-sandbox/auto-review/SRT file+test map；apply-seccomp source/binary hashes/build contract；Docker migration map；CodeGraph impact；O/S/L/M/P/R tests, commands, prerequisites；offline baseline 406 passed |
