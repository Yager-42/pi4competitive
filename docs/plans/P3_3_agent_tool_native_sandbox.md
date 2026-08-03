# Plan: P3.3 — Native AgentTool sandbox

| Field | Value |
|-------|-------|
| **plan_id** | `P3.3-agent-tool-native-sandbox` |
| **plan_version** | `0.1.6` |
| **status** | **complete — A–F + V1 + V3（macOS real gate）+ V4（audits/baseline/closeout）done；V2 optional per ADR 0013（未运行，Linux deploy 前必过）** |
| **created** | 2026-08-02 |
| **updated** | 2026-08-03 |
| **roadmap** | [`docs/ROADMAP.md`](../ROADMAP.md) stage P3.3 |
| **contract** | [`ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) v0.3.10 |
| **ADR** | [`0012-native-agent-tool-sandbox-runtime.md`](../contracts/adr/0012-native-agent-tool-sandbox-runtime.md) accepted |
| **feature** | [`agent_tool_native_sandbox_v1.md`](../features/agent_tool_native_sandbox_v1.md) frozen v0.2.2 |
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
native/vendor/                        # G0 §5 apply-seccomp supply chain (COPY)
  seccomp/
    x64/apply-seccomp                 # npm-published binary, sha256 pinned
    arm64/apply-seccomp               # npm-published binary, sha256 pinned
  seccomp-src/
    apply-seccomp.c                   # frozen source (provenance only)
    seccomp-unix-block.c
    LICENSE
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
    workspace.py                     # ADAPT of docker_path_guard workspace helpers
    paths.py                         # identity translator + fixed-command guard
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
| B | Python SRT config/policy/Linux/macOS/seccomp/proxy port | **done — PR2 gate passed (O11–O15; offline 660 passed)** |
| C | erichll runner/broker/network approval port | **done — PR3 gate passed (O16 + approval/config parity; offline 718 passed)** |
| D | NativeProvider/Runtime + current worker/registry/RPC integration | **done — O17–O18 passed; offline 738 passed** |
| E | App wiring/readiness/scope lifecycle + Linux/macOS config | **done — O19–O21 passed；offline 743 passed** |
| F | remove Docker production code/dependencies/image/config | **done — G0 §6.2 executed；agent-sandbox dep removed；offline 715 passed** |
| V1 | offline contract/unit/parity tests | **done — O1–O22 green；offline 715 passed** |
| V2 | Linux amd64 real enforcement/e2e | **optional（ADR 0013）**— Linux 主机/CI 可用时运行同一 S1–S9 套件；不阻塞 closeout；任何 Linux production 部署声明前必过 |
| V3 | arm64 macOS real enforcement/e2e | **done — S1–S9 + e2e 11 tests green（real broker + real policy, sandbox-exec）；gate 修复 2 个 production 缺陷：interpreter symlink exec（policy.py/macos.py）、AF family 映射（network_policy.py）；offline 727 passed** |
| V4 | baseline/resource/license/CodeGraph audit and closeout | **done — plan §5.4 evidence vs ADR 0012 Docker（cold 0.109 s vs 1.386 s；steady P50 108.9 ms/P95 110.4 ms；10-way parallel 0.85 s、in-flight 10 brokers 361 MiB；residual 0；disk 2.0 MB vs 12.1 GB image）；license 补回 pi-sandbox Apache + pi-auto-review MIT（SHA 对齐 G0 pin，O22 全量断言）；header 全绿；CodeGraph sync（460 files/5719 nodes）；§7 全勾选；offline 727 passed** |

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

- bubblewrap mount/network/PID namespace 和 nested seccomp active；
- workspace allow；home/App/session/DB/other scope deny；
- network default deny, public exact grant allow, private/mixed DNS deny；
- parallel calls overlap with independent brokers；
- timeout/abort/scope abort leave no process/proxy orphan.

### 5.3 macOS real

- Seatbelt profile active with equivalent filesystem/network decisions；
- same approval, parallel, timeout, abort and cleanup behavior；
- no unsupported-path Host fallback.

- **V3 executed 2026-08-03（arm64 macOS, sandbox-exec 真实执行）**：S1–S9 +
  parallel/abort e2e 11 tests green（`tests/competitive_app/integration/live/
  test_macos_sandbox_enforcement.py`，驱动 real broker + real
  `create_default_policy`）。gate 期间发现并修复两个 production 缺陷：
  - `srt/macos.py` + `policy.py`：venv interpreter 经 symlink 链落在
    `denyRead=[home]` 之下，Seatbelt 解析 symlink 后 execvp EPERM —
    `policy.py` 将 interpreter symlink 链每一跳 dirname + 最终 bin/base
    加入 allowRead；`macos.py` 对 allowWithinDeny 被 deny 的每个祖先目录
    补发 literal `file-read-metadata`（wildcard allow 无法 re-grant exec）。
  - `native/network_policy.py`：`_default_resolver` 返回 AF_INET/AF_INET6
    (2/30) 而 `is_public_address` 期望 ipaddress version (4/6)，导致
    validate 恒 None、broker 永不发出 network-request（approval 通路
    静默失效）— 现映射为 4/6，回归测试走 real resolver（fake
    getaddrinfo，offline）。


> **ADR 0013（contract v0.3.10）**：§5.2 Linux real gate 为**可选项** —
> Linux amd64 主机/CI 可用时运行；任何 Linux production 部署声明前必须
> 通过；不阻塞 P3.3 closeout。§5.3 macOS real gate 保持正式必过。
> Linux production 真实行为（bubblewrap/seccomp 生效）在可选 gate 通过前
> 记录为未验证残余风险（feature §11.2）。

### 5.4 V4 evidence（2026-08-03, arm64 macOS, Apple M4）

| Metric | Native（measured） | Frozen Docker baseline（ADR 0012） |
|--------|--------------------|-----------------------------------|
| cold first call | **0.109 s**（broker spawn + 81KB profile + sandbox-exec） | 1.386 s |
| steady P50 / P95（n=15, `echo hi`） | **108.9 ms / 110.4 ms** | warm 35–60 ms |
| 10-way parallel（in-flight） | **0.85 s wall**（10 brokers live, `sleep 0.6` cmds） | — |
| in-flight RSS per broker | **~37 MiB**（10 × 37 = 361 MiB total） | idle 332 MiB / 31 PIDs |
| residuals after calls / abort | **0 processes**（8/8 disconnect-clean + ps clean） | — |
| disk | **2.0 MB** native tree; no image | image **12.1 GB** |

No artificial latency SLA（G0 §8.4）; per-call isolation（broker per call）is the
design tradeoff behind the steady 109 ms vs Docker warm reuse. G0 §8.4 P1–P5
evidence recorded in the V4 commit.

### 5.5 Comparison and removal

P3.3 closes only after the Docker provider/backend/runtime/image/SDK/config are removed and the dependency/license audits are green (Phase F removal + V4).


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

- [x] Frozen source archives/SHAs/package versions/licenses recorded.
- [x] COPY/ADAPT/OMIT map matches actual files and host deltas.
- [x] Python approval core matches exact grant/hard-deny/failure-mode semantics.
- [x] macOS SRT path passes the real enforcement gate (V3, arm64) — **required**.
- [x] Linux SRT path real enforcement gate is **optional** (ADR 0013): runs
      when a Linux host/CI is available; required before any Linux production
      deployment claim; does not block closeout.
- [x] Universal AgentTool execution, RPC, registry, scope/workspace remain green.
- [x] Abort/timeout/parallel leave no orphan.
- [x] Worker environment remains the seven-item allowlist.
- [x] Docker provider/backend/runtime/image/SDK/config removed; no fallback.
- [x] Full offline suite, contract drift, import boundaries and CodeGraph audit green.
- [x] Roadmap P3.3 marked done only after every item above is checked.

## 8. Revision history

| Version | Date | Change |
|---------|------|--------|
| `0.1.0` | 2026-08-02 | Initial active plan from ADR 0012 / native feature v0.2.0; preserves current executor/RPC/scope, ports three frozen upstreams, replaces and removes Docker, and defines Linux/macOS real gates |
| `0.1.1` | 2026-08-02 | G0 complete：pins Git/npm integrity/licenses；full pi-sandbox/auto-review/SRT file+test map；apply-seccomp source/binary hashes/build contract；Docker migration map；CodeGraph impact；O/S/L/M/P/R tests, commands, prerequisites；offline baseline 406 passed |
| `0.1.2` | 2026-08-02 | Phase E complete：wiring/readiness manifest staging/startup verify、O20 universal-executor coverage（main/dynamic/extension/resume/ephemeral over real worker+capability）、offline 743 passed |
| `0.1.3` | 2026-08-02 | Phase F complete：G0 §6.2 all rows executed — docker/、runtimes/、translators/、guards/、deploy/tool-sandbox/ deleted；agent-sandbox==0.0.30 removed from pyproject/uv.lock；licenses moved to native/vendor/licenses；retained headers repointed；test_backend/test_docker_provider/Docker live suite deleted；facade/contract tests adapted；O22 native contract suite added；wiring E1.4 unwind widened to cover manifest-write failure；V1 green offline 715 passed |
| `0.1.4` | 2026-08-03 | **ADR 0013**：V2 Linux real gate 改为可选项（不阻塞 closeout；Linux production 部署前必过；apply-seccomp 供应链契约不变）；V3 macOS real gate 正式必过（进行中）；roadmap/feature/contract 同步 v0.3.10 |
| `0.1.5` | 2026-08-03 | **V3 macOS real gate done**：S1–S9 + parallel/abort e2e 11 tests green（real broker/policy/sandbox-exec）；修复 interpreter symlink-exec（policy.py 加 symlink 链 allowRead；macos.py 补 literal file-read-metadata 祖先目录）与 network_policy AF family 映射（approval 通路回归）；offline 727 passed；V4 audits 进行中 |
| `0.1.6` | 2026-08-03 | **V4 closeout done**：resource baseline vs ADR 0012 Docker（cold 0.109 s vs 1.386 s；steady P50 108.9 ms/P95 110.4 ms；10-way parallel 0.85 s、in-flight 10 brokers 361 MiB；residual 0；disk 2.0 MB vs image 12.1 GB）；license audit — 补回 pi-sandbox Apache 与 pi-auto-review MIT 文本（SHA 对齐 G0 pin，O22 全量 pin 断言）；header audit 全绿；CodeGraph sync；§7 全勾选；offline 727 passed |
