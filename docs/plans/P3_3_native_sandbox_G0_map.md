# P3.3 Native Sandbox G0 Source, Migration, and Test Map

| Field | Value |
|-------|-------|
| **map_version** | `0.1.0` |
| **status** | **frozen G0 evidence — complete** |
| **date** | 2026-08-02 |
| **plan** | [`P3_3_agent_tool_native_sandbox.md`](P3_3_agent_tool_native_sandbox.md) v0.1.3 |
| **ADR** | [`0012-native-agent-tool-sandbox-runtime.md`](../contracts/adr/0012-native-agent-tool-sandbox-runtime.md) |
| **feature** | [`agent_tool_native_sandbox_v1.md`](../features/agent_tool_native_sandbox_v1.md) v0.2.1 |

This file is the binding G0 appendix. Implementation may not silently change a source classification, destination, test ID, helper artifact, or removal decision; update this map first and record the host delta in the active plan.

> Execution status (2026-08-02, Phase F): §6.1 keep/adapt rows landed in
> phases C–E; §6.2 deletion rows were all executed — `docker/`, `runtimes/`,
> `translators/`, `guards/`, `deploy/tool-sandbox/` removed, the three
> orphaned contracts files deleted after an rg gate showed no non-Docker
> caller, `agent-sandbox==0.0.30` removed from pyproject/uv.lock, and the
> Poirot license text moved to `native/vendor/licenses/` with every
> retained header repointed (the agent-sandbox license text had no
> retained referent and was removed with the dependency). Decisions below
> remain frozen; this note records execution only.

> ADR 0013 (2026-08-03, contract v0.3.10, feature v0.2.2, plan v0.1.4):
> §8.2 的 S1–S9 仍是唯一的 real-enforcement ID 集，但 Linux 执行由正式必过
> gate 改为可选项（Linux 主机可用时运行；Linux production 部署声明前必过；
> 不阻塞 P3.3 closeout）；macOS（arm64）S1–S9 真实执行保持正式必过 gate。
> §5.1/5.2 的 apply-seccomp 供应链与 startup 校验契约不变；其真实执行属
> Linux 可选 gate。本注记不改变任何 source/test/removal 分类。

> V3 execution (2026-08-03, arm64 macOS, real sandbox-exec): §8.2 S1–S9 and
> §8.3 M1–M4 executed via `tests/competitive_app/integration/live/
> test_macos_sandbox_enforcement.py` (11 tests, NOT live-marked: the macOS
> host is the required gate, skipped on other platforms) driving the real
> broker process with the real `create_default_policy` + SRT runtime
> config. Two production defects found and fixed, both host-delta recorded
> in the affected module headers: (1) interpreter symlink chain under
> `denyRead=[home]` broke exec (`policy.py` allowRead symlink hops +
> `macos.py` literal `file-read-metadata` ancestor allows); (2)
> `network_policy.py` `_default_resolver` returned AF constants (2/30)
> where `is_public_address` expects ipaddress versions (4/6), silently
> disabling the approval round trip. Regression test added to O4's file.
> `network_policy.py` family mapping is a port-only defect (upstream never
> resolves through `isIP` family checks).

> V4 execution (2026-08-03): §8.4 P1–P5 evidence recorded in plan §5.4
> (same-host arm64 macOS vs the frozen ADR 0012 Docker baseline: cold
> 0.109 s vs 1.386 s; steady P50 108.9 ms / P95 110.4 ms; 10-way parallel
> 0.85 s with 10 in-flight brokers at ~37 MiB RSS each = 361 MiB total vs
> Docker idle 332 MiB/31 PIDs; zero residual processes after calls and
> after parent-disconnect abort; 2.0 MB native tree, no image, vs 12.1 GB).
> License audit: two upstream license texts were missing from the native
> license directory (pi-sandbox Apache-2.0, pi-auto-review MIT) — now
> retained verbatim as `PI-SANDBOX-APACHE-2.0.txt` / `AUTO-REVIEW-MIT.txt`,
> SHA-256 matching the §1.2 pins; `vendor/LICENSE` (SRT Apache text) moved
> to `licenses/SRT-APACHE-2.0.txt`; O22 pins all four texts. Header audit
> green; CodeGraph re-synced (460 files / 5,719 nodes); plan §7 fully
> checked; roadmap P3.3 = done.

## 1. Immutable Source Manifest

### 1.1 Published artifacts and repository identities

| Source | Repository / commit | Registry artifact | Integrity | License |
|--------|---------------------|-------------------|-----------|---------|
| `@erichll/pi-sandbox@0.4.2` | `erichll/pi-packages@10c8eeb8269ee478ff7383c7e6139301aa9665f9` | `https://registry.npmjs.org/@erichll/pi-sandbox/-/pi-sandbox-0.4.2.tgz` | `sha512-tXfSNb98JdpDq7SUPQbaBfRZ/Z0i1qO9WndETG3LJtw/FZjrmfVyHL9J6EMcHGpbnrYEpZJ1NhNKJNjbnpWNAA==` | Apache-2.0 |
| `@erichll/pi-auto-review@0.3.2` | same monorepo commit | `https://registry.npmjs.org/@erichll/pi-auto-review/-/pi-auto-review-0.3.2.tgz` | `sha512-ex+qghPINpXS7mfdTdfiFAaCI+tjEwlWAZ1VILF9uXHehv5FUuuZsQvybWpYtztp9q9PVBDVpYH3UHsO7M6aGA==` | MIT |
| `@anthropic-ai/sandbox-runtime@0.0.67` | tag `v0.0.67` @ `21d8f75e1bc00eede09b3103e68b2eae097110d1` | `https://registry.npmjs.org/@anthropic-ai/sandbox-runtime/-/sandbox-runtime-0.0.67.tgz` | `sha512-4doSyr6KNdc/4zARMXYEawhFu3z6bPQjgKRq3lKp6dbgEYVMv39oaLJ28QsDc7TmLvrLqzHW+VzD2LAXxvnw8A==` | Apache-2.0 |

Registry metadata was queried for the exact versions on 2026-08-02. Floating tags, semver ranges, later tarballs, forks, and locally rebuilt package archives are not source substitutes.

### 1.2 Checked source metadata hashes

| File | SHA-256 |
|------|---------|
| `pi-sandbox/LICENSE` | `dc5a2fe270e7aa045d017d0c7aa7c0d9052f6fc888695df34531db69c06b7d28` |
| `pi-sandbox/package.json` | `cc7ded3d1cc0373cc01fae69aa8cfbf4c8641f9ab11f5626d40250e83387c7bf` |
| `pi-auto-review/LICENSE` | `1126322e2cc8d165adc4c792eeb195717de2bcc7b39be1ce77959d78e87ef685` |
| `pi-auto-review/package.json` | `43a3a5d08a38cc5f2c19945e4f071c153cc54e3bf6d65abb03a2fcfe4698fec5` |
| SRT `LICENSE` | `1210bc93eb85dd786c33192d5bcb7153a93922fa99fbc1512af6a7199cb41080` |
| SRT `package.json` | `ee3066dbb74db4a42d4a6411eb9d49a423eebaa925adcdb5f733b6089d35e30c` |

Every copied or materially adapted Python file must include source package/version/path/commit, license, and a succinct host-delta header. License texts must be retained under a native sandbox license directory after the historical Docker directory is removed.

## 2. `pi-sandbox@0.4.2` Complete File Map

### 2.1 Source

| Upstream file | Mode | Python destination / reason |
|---------------|------|-----------------------------|
| `src/runner.ts` | ADAPT | `native/runner.py`; Node fork/events -> asyncio subprocess/IPC; preserve detached tree, timeout, abort, finally kill, network messages |
| `src/srt-broker.mjs` | ADAPT | `native/broker.py`; Python broker and current worker target; preserve one init, initialize/wrap/reset, stdio, exit 1 |
| `src/policy.ts` | ADAPT | `native/policy.py`; preserve policy/secret scan; Node roots -> trusted Python/tool bundle roots |
| `src/config.ts` | COPY-semantics | `native/config.py`; strict shape, unknown key rejection, trusted paths; omit Host IPC/subagent product fields from accepted native schema |
| `src/network-policy.mjs` | COPY-semantics | `native/network_policy.py`; hostname normalization and all-address public DNS validation |
| `src/network-policy.d.mts` | OMIT | Type declaration only; Python types live with implementation |
| `src/approval.ts` | ADAPT | `native/approval.py`; generic Pi broker DI; preserve hard deny/unavailable/invalid-grant outcomes |
| `src/traps.ts` | COPY-semantics | App sandbox trap types/formatter |
| `src/index.ts` | OMIT/TRANSPLANT TESTS | Pi extension/Bash registration replaced by universal executor; relevant integration behavior moves to App tests |
| `src/subagent.ts` | OMIT/TRANSPLANT TESTS | Existing ephemeral sub-agent owns orchestration and inherits parent executor/scope |
| `src/host-ipc.ts` | OMIT | Host execution violates native-only/no-host-fallback |

### 2.2 Tests

| Upstream test | Disposition |
|---------------|-------------|
| `approval.test.ts` | PORT to `test_native_approval.py` |
| `config.test.ts` | PORT to `test_native_config.py` |
| `macos.test.ts` | PORT behavior into macOS real/profile tests |
| `network-policy.test.ts` | PORT vectors verbatim to `test_network_policy.py` |
| `policy.test.ts` | PORT to `test_native_policy.py` |
| `runner.test.ts` + `fixtures/srt-broker.mjs` | PORT to runner/broker fixture tests |
| `traps.test.ts` | PORT to App approval adapter tests |
| `extension.test.ts` | ADAPT assertions to universal executor/App integration |
| `coexistence.test.ts` | ADAPT to local capability + sandbox composition test |
| `subagent.test.ts` | ADAPT only isolation/scope assertions into existing ephemeral tests; omit duplicate orchestration product |
| `host-ipc.test.ts` | OMIT and replace with negative contract test proving no Host IPC symbol/config/path exists |

## 3. `pi-auto-review@0.3.2` Complete File Map

### 3.1 Source

| Upstream file | Mode | Python destination / reason |
|---------------|------|-----------------------------|
| `src/broker/types.ts` | COPY-semantics | generic contract in `packages/agent` (`boundary_approval.py`); concrete review/audit types in `pi_auto_review/types.py` |
| `src/broker/broker.ts` | ADAPT | `pi_auto_review/broker.py`; preserve validate -> hard deny -> breaker -> reviewer -> exact grant; denials/override paths absent (overrides.ts OMIT) |
| `src/broker/grants.ts` | COPY-semantics | `pi_auto_review/grants.py`; stable canonical hash, TTL, one-use store |
| `src/broker/circuit-breaker.ts` | COPY-semantics | `pi_auto_review/circuit_breaker.py`; same consecutive and rolling denial thresholds |
| `src/broker/service.ts` | ADAPT | generic service publication/lookup in `packages/agent` `boundary_approval.py`; App receives explicit injected contract |
| `src/broker/index.ts` | ADAPT | `pi_auto_review/__init__.py` Python exports only |
| `src/broker/overrides.ts` | OMIT | No current user retry/TUI entry; no dormant override store |
| `src/integrations/sandbox.ts` | COPY-semantics | App trap -> generic boundary request adapter |
| `src/policy.ts` | ADAPT | `pi_auto_review/policy.py`; strict parser, hard deny, bounded/redacted/escaped evidence using Python Pi messages |
| `src/config.json` | COPY | `pi_auto_review/config.json` (package defaults; trusted overlays may only tighten project-side values) |
| `src/index.ts` | SPLIT/ADAPT | trusted config/model reviewer/trust checks -> `pi_auto_review/reviewer.py`; extension registration -> `extensions/register.py` (NEW-HOST entry: loader imports one entry .py per capability, so siblings live in the importable `pi_auto_review/` subpackage under the capability root; user-global `~/.pi` overlay replaced by `AUTO_REVIEW_*` env, the established App config channel); permission-system/TUI glue omitted |
| `src/ui-auto-confirm.ts` | OMIT | No coding TUI contract |
| `src/user-feedback.ts` | OMIT | No footer/toast UI contract |

### 3.2 Tests

| Upstream test | Disposition |
|---------------|-------------|
| `broker.test.ts` | PORT all validation/reviewer/grant/breaker cases |
| `policy.test.ts` | PORT strict decision, hard deny, transcript/evidence/redaction vectors |
| `sandbox.test.ts` | PORT trap conversion vectors |
| `trust.test.ts` | PORT trusted install/config tighten-only cases |
| `override.test.ts` | OMIT; negative test confirms override API absent |
| `authorizer-integration.test.ts` | ADAPT only generic Pi service publication/injection; omit external permission-system/TUI chain |
| `user-feedback.test.ts` | OMIT |
| `typescript-loader.mjs` | OMIT test infrastructure |

## 4. SRT `0.0.67` Complete File Map

The official tag contains 36 TypeScript runtime files. Static imports in `sandbox-manager.ts` include optional credential/TLS/Windows products that erichll never configures. The Python manager must port the runtime closure exercised by erichll, not preserve unused static imports.

### 4.1 Full or behavior-complete ports

| Upstream file | Mode / Python responsibility |
|---------------|------------------------------|
| `src/sandbox/sandbox-manager.ts` | ADAPT narrow manager: initialize/wrap/cleanup/reset, platform dispatch, proxy lifecycle, ask callback, violation lifecycle; remove unused optional imports |
| `src/sandbox/sandbox-config.ts` | ADAPT strict filesystem/network/seccomp subset; unsupported credential/TLS/Windows fields rejected, not ignored |
| `src/sandbox/sandbox-schemas.ts` | COPY-semantics required filesystem/network restriction shapes |
| `src/sandbox/linux-sandbox-utils.ts` | ADAPT complete erichll-used Linux dependency check, bwrap argv, bridge, mandatory deny scan, cleanup, nested seccomp |
| `src/sandbox/macos-sandbox-utils.ts` | ADAPT complete erichll-used Seatbelt profile/argv/log monitor path |
| `src/sandbox/sandbox-utils.ts` | COPY-semantics path normalization, dangerous paths, glob/symlink/proxy env helpers used by Linux/macOS |
| `src/sandbox/generate-seccomp-filter.ts` | ADAPT architecture/helper resolution and hash verification; build logic recorded in §5 |
| `src/sandbox/domain-pattern.ts` | COPY-semantics domain canonicalization/matching |
| `src/sandbox/http-proxy.ts` | ADAPT standard HTTP + CONNECT allow-callback path; omit unconfigured TLS termination/body mutation/SigV4 branches |
| `src/sandbox/socks-proxy.ts` | ADAPT SOCKS hostname validation, auth token, allow callback, direct/parent routing |
| `src/sandbox/mux-proxy.ts` | ADAPT first-byte dispatch and deterministic cleanup |
| `src/sandbox/listen-in-range.ts` | COPY-semantics bounded port selection |
| `src/sandbox/parent-proxy.ts` | ADAPT host validation, direct dial, configured parent proxy/NO_PROXY behavior without exposing env to worker |
| `src/sandbox/linux-violation-monitor.ts` | ADAPT violation socket/parser/lifecycle |
| `src/sandbox/sandbox-violation-store.ts` | COPY-semantics bounded violation store |
| `src/utils/debug.ts` | ADAPT Python logging without args/secrets |
| `src/utils/platform.ts` | ADAPT Linux/macOS only; Windows/WSL product branches rejected |
| `src/utils/ripgrep.ts` | ADAPT asyncio subprocess and abort |
| `src/utils/shell-quote.ts` | COPY-semantics golden vectors |
| `src/utils/which.ts` | ADAPT Python executable discovery |
| `src/index.ts` | OMIT module facade; native package exports explicit Python symbols |

### 4.2 Partial optional branches explicitly omitted

| Upstream file | Reason |
|---------------|--------|
| `src/sandbox/request-filter.ts` | erichll runtime config supplies no per-request HTTP content filter |
| `src/sandbox/body-substitution.ts` | no credential/body substitution config |
| `src/sandbox/tls-terminate-proxy.ts` | erichll does not enable TLS termination |
| `src/sandbox/mitm-ca.ts`, `mitm-leaf.ts` | TLS termination/credential injection unused |
| `src/sandbox/credential-sentinel.ts` | erichll config does not register credential sentinels |
| `credential-mask-env.ts`, `credential-mask-files.ts` | no SRT credential masking config; worker keeps current seven-item allowlist |
| `credential-extract.ts`, `credential-decode.ts` | only used by omitted masking paths |
| `credential-aws-pairs.ts`, `aws-sigv4.ts` | no AWS credential rewriting |
| `src/sandbox/windows-sandbox-utils.ts` | Linux/macOS feature scope only |
| `src/utils/config-loader.ts`, `src/cli.ts` | SRT CLI product omitted; App trusted config owns loading |

Every omitted branch gets an offline negative configuration test: supplying its field must fail validation instead of silently weakening or pretending support.

### 4.3 SRT upstream test transplant selection

PORT/ADAPT: `config-validation`, `configurable-proxy-ports`, `control-fd`, `allow-read`, `check-dependencies`, `connect-non-tls`, `filesystem-disabled`, `glob-expand`, `integration`, Linux bridge/dependency/violation tests, macOS local-binding/apple-events/pty/Seatbelt tests, mandatory deny paths, mux/parent proxy tests, PID namespace, proxy env, seccomp, symlink tests, update-config, wrap-with-sandbox, and platform/ripgrep/shell-quote/which tests.

OMIT with negative unsupported-config coverage: AWS/SigV4, body substitution, credential mask/deny/injection, MITM/TLS termination, Windows, and CLI tests.

## 5. `apply-seccomp` Supply Chain

### 5.1 Frozen source and published binaries

| Artifact | SHA-256 / identity |
|----------|-----------------------|
| `vendor/seccomp-src/apply-seccomp.c` | `072c37535d88196a5cae870f1adfc884080c4a92e20e39042b7eb81c54cf100b` |
| `vendor/seccomp-src/seccomp-unix-block.c` | `6802faf04898a488d0ba1d512ef23fc65a43545c017a8d516a567063a2b315dc` |
| npm arm64 `apply-seccomp` | `0bec512e784caf7d87f60783ece6480e1340b1ecd38f30b1d6d79d7e794cefb4`; static ELF aarch64; BuildID `749e4a9a28ebce5216f7eb7b5c23ab89b791ff32` |
| npm x64 `apply-seccomp` | `8e0c58e1ccb0fed7c7d95295773204a2b7e7235c14feac934d7812e7fb2017ab`; static ELF x86-64; BuildID `85e97143c74bdc3dc031b762a6935575592fcdb9` |

Destination (map update — permit rule): runtime vendor tree is
`competitive_app/src/competitive_app/adapter/out/sandbox/native/vendor/`
(`seccomp/{x64,arm64}/apply-seccomp` + `seccomp-src/` + `LICENSE`), resolved
by `srt/seccomp.py` relative to the native package root; explicit
`seccomp.applyPath` still overrides. The plan §3 layout was updated to match
before any code landed.

### 5.2 Build and verification contract

1. Runtime packages the exact npm-published binary for `x64` and `arm64`; startup verifies architecture, executable bit, and the SHA-256 above before Linux readiness.
2. Source, upstream `vendor/seccomp/build.ts`, both C files, Apache-2.0 license, and hashes are retained as provenance. Production does not invoke Node or compile at startup.
3. Linux build-verification CI installs `gcc`, static libc tooling, and `libseccomp-dev`, then reproduces upstream steps: static `seccomp-unix-block`, emit x86_64/aarch64 BPF header, static `apply-seccomp`, strip.
4. Compiler/build-id variation means rebuilt binary need not be byte-identical. CI must execute upstream seccomp behavior tests: AF_UNIX denied, `io_uring_setup/enter/register` denied, nested user/PID/mount namespace created, `/proc` remounted, PID1 non-dumpable/reaps, and nested setup failure aborts.
5. Unsupported Linux architecture fails readiness; `allowAllUnixSockets` is not exposed as a production weakening switch.

## 6. Current Repository Migration Map

### 6.1 Keep or adapt

| Current target | Decision |
|----------------|----------|
| `packages/agent/.../tool_execution.py` and executor/scope propagation | KEEP; add generic boundary service separately |
| `approved_registry.py`, `protocol.py` | KEEP |
| `worker.py`, `sandbox_tool_executor.py`, `lifecycle.py`, `exceptions.py`, `types.py` | ADAPT to native paths/signal/active invocation/readiness |
| `contracts/sandbox_provider.py`, `contracts/sandbox_runtime.py` | ADAPT provider-neutral native lifecycle/worker contract |
| `native/native_runtime.py`, `native/native_sandbox_provider.py` | NEW-HOST (Phase D): SandboxRuntime + SandboxProvider over the broker runner; per-scope abort signal, workspace lifecycle, worker env allowlist |
| `native/workspace.py` | ADAPT of `guards/docker_path_guard.py` workspace helpers (canonical root/ensure/remove); Docker path validation stays with the deleted guard |
| `native/paths.py` | NEW-HOST (Phase D): identity PathTranslator + fixed-worker-command SecurityGuard for the runtime-only Sandbox facade |
| `sandbox.py` | ADAPT to runtime-only native handle; remove Docker translator/guard composition |
| `utils/sandbox_id.py` | KEEP behavior; update provenance comment only if needed |
| `tests/.../test_approved_registry.py`, `test_protocol.py`, `test_worker.py`, `test_facade.py`, `test_composition.py` | KEEP/ADAPT |
| `tests/competitive_app/contract/test_sandbox_contract.py` and package dependency contracts | ADAPT to ADR 0012 |

### 6.2 Delete or replace before closeout

| Current target | Decision |
|----------------|----------|
| `adapter/out/sandbox/docker/**` | DELETE all: provider, backend, executor, readiness, cross-process Docker lock, exports |
| `adapter/out/sandbox/runtimes/docker_runtime.py` | DELETE; replace runtime exports with native |
| `adapter/out/sandbox/translators/docker_path_translator.py` | DELETE |
| `adapter/out/sandbox/guards/docker_path_guard.py`, `audit_guard.py` | DELETE from production; native policy/logging tests replace |
| `contracts/path_translator.py`, `security_guard.py`, `sandbox_backend.py` | DELETE if no non-Docker caller remains; CodeGraph/rg gate required immediately before removal |
| `deploy/tool-sandbox/**` | DELETE Dockerfile, manifest, init package, historical embedded licenses after native notices are installed elsewhere |
| `competitive_app/pyproject.toml`, root `uv.lock` | REMOVE `agent-sandbox==0.0.30` and lock entries |
| `wiring.py` / config | REPLACE Docker imports, `sandbox.image`, `SANDBOX_IMAGE`, image verification with native trusted config/readiness |
| `test_backend.py`, `test_docker_provider.py` | DELETE after native provider/runtime parity replacements exist |
| `integration/live/test_live_sandbox_security.py` | REPLACE with Linux/macOS native real suites |
| Docker-only portions of `test_composition.py` | REPLACE with native composition/readiness cases |

No historical source/license notice may be deleted until `rg` proves no retained file still declares Poirot or agent-sandbox provenance.

## 7. CodeGraph Impact Evidence

G0 ran against the up-to-date index (`428 files`, `5,037 nodes`, `12,058 edges` before doc-only additions):

| Query | Result |
|-------|--------|
| `codegraph impact SandboxToolExecutor` | direct affected file: `competitive_app/.../wiring.py` |
| `codegraph impact DockerSandboxProvider` | direct affected file: `competitive_app/.../wiring.py` |
| `codegraph impact DockerRuntime` | symbol not found by index; use explicit file/rg audit |
| `codegraph affected` on executor/lifecycle/worker/wiring | no tests reported |

The empty affected result is an index limitation, not permission to skip tests. Explicit mandatory consumers are wiring, session/task lifecycle, current sandbox unit/contract suites, live security suite, ephemeral harness construction, abort/delete workspace paths, `competitive_app/pyproject.toml`, `uv.lock`, and `deploy/tool-sandbox`.

Before every exported-symbol removal, rerun `codegraph callers/impact`; after adding native modules run `codegraph sync`; before PR5 run both CodeGraph and full `rg` deletion audits.

## 8. Frozen Test Matrix

### 8.1 Offline IDs and target files

| IDs | Target file(s) | Required behavior |
|-----|----------------|-------------------|
| O1–O3 | `tests/competitive_app/unit/sandbox/native/test_config.py`, `test_policy.py` | strict config, secret policy, unsupported fields fail |
| O4–O5 | `.../test_network_policy.py`, `test_traps.py` | hostname/IP/DNS vectors and trap mapping |
| O6–O9 | `tests/capability_packages/pi_auto_review/test_{grants,circuit_breaker,policy,broker}.py` | exact hash/TTL/use, breaker, decision/hard deny/evidence, reviewer outcomes |
| O10 | `tests/packages/agent/unit/test_boundary_approval.py` | generic service publication/lifetime/no App dependency |
| O11–O15 | `tests/competitive_app/unit/sandbox/native/test_srt_{config,linux,macos,proxy,seccomp}.py` | upstream argv/profile/proxy/seccomp golden vectors |
| O16–O18 | `.../test_{runner,broker,native_provider}.py` | IPC, timeout/abort/tree cleanup, independent concurrency |
| O19 | existing registry/protocol/worker suites | current RPC and target behavior unchanged |
| O20 | `tests/competitive_app/integration/test_native_sandbox_coverage.py` | main/dynamic/extension/resume/ephemeral universal executor |
| O21 | `tests/competitive_app/unit/sandbox/test_composition.py` | explicit broker DI, readiness failure unwind, no fallback |
| O22 | `tests/competitive_app/contract/test_native_sandbox_contract.py` | ownership/import/config/no Docker/Host IPC contract |

### 8.2 Common real security IDs

| IDs | Behavior |
|-----|----------|
| S1–S3 | workspace rw; tool bundle ro; Host home/App/session/DB/other scope deny |
| S4–S5 | traversal/symlink boundary; existing and root-level new secret deny |
| S6–S8 | network default deny; exact public endpoint grant; private/loopback/link-local/metadata/mixed DNS deny |
| S9 | grant change/expiry/reuse and reviewer failure/defer deny |
| S10 | broker/SRT/target crash never executes Host or Docker |
| S11 | timeout, call abort, scope abort kill complete tree/proxy with no orphan |
| S12 | same/cross scope parallel calls overlap and isolate correctly; idle has zero broker/worker/proxy |

### 8.3 Platform IDs

| IDs | Platform evidence |
|-----|-------------------|
| L1–L2 | Linux bwrap mount/network/PID namespace and mandatory paths verified from inside worker |
| L3 | published `apply-seccomp` blocks AF_UNIX/io_uring and establishes nested PID/mount namespace |
| L4 | dependency/nested namespace/bridge failure aborts; violation monitor cleanup |
| L5 | Linux production App echo + faux-approved network tool e2e |
| M1–M2 | macOS generated Seatbelt profile active; filesystem behavior verified, not argv-only |
| M3 | macOS proxy-only network and exact approval behavior |
| M4 | macOS timeout/abort/parallel/cleanup no orphan |
| M5 | macOS production App echo + faux-approved network tool e2e |

### 8.4 Performance/removal IDs

| IDs | Evidence |
|-----|----------|
| P1–P3 | same-host cold, steady P50/P95, 10-way parallel latency/RSS/PIDs |
| P4 | idle scope broker/worker/proxy/container count and RSS/PIDs |
| P5 | installed/runtime disk size and abort orphan count |
| R1–R4 | no Docker production imports/config/dependency/image/tests; no Host IPC; licenses retained; CodeGraph/rg clean |

## 9. Commands and Host Prerequisites

### 9.1 Offline baseline and required command

```bash
TAVILY_API_KEY=offline-test UV_CACHE_DIR=/tmp/pi4competitive-uv-cache uv run pytest -m "not live" -q
```

G0 result on 2026-08-02: **406 passed, 47 deselected, 2 warnings in 5.69s**. It required permission to bind a loopback test server. An initial filesystem-sandboxed run produced the expected environment-only `PermissionError` at `asyncio.start_server`; it is not a repository failure.

### 9.2 Linux amd64 real gate

Prerequisites: Python 3.12+, x86_64 Linux, `bubblewrap`, `socat`, `ripgrep`, unprivileged user namespaces permitted, seccomp enabled, frozen x64 helper executable/hash valid. `gcc` + static libc + `libseccomp-dev` are additionally required only for source-build verification.

```bash
UV_CACHE_DIR=/tmp/pi4competitive-uv-cache uv run pytest -m "native_sandbox and linux" -q
```

### 9.3 arm64 macOS real gate

Prerequisites: Python 3.12+, arm64 macOS, `/usr/bin/sandbox-exec`, `ripgrep`, loopback sockets. No Docker daemon and no Linux helper are permitted as hidden prerequisites.

```bash
UV_CACHE_DIR=/tmp/pi4competitive-uv-cache uv run pytest -m "native_sandbox and macos" -q
```

### 9.4 Full closeout

```bash
TAVILY_API_KEY=offline-test UV_CACHE_DIR=/tmp/pi4competitive-uv-cache uv run pytest -m "not live" -q
UV_CACHE_DIR=/tmp/pi4competitive-uv-cache uv run pytest -m native_sandbox -q
codegraph sync
codegraph status
```

Marker registration must be added to pytest configuration in the first implementation slice. A live model reviewer may be recorded as sanitized diagnostic evidence, but deterministic pass/fail uses the existing faux model provider; OS isolation and network proxy tests remain real.

## 10. Frozen Existing Performance Baseline

| Metric | Docker/AIO baseline |
|--------|---------------------|
| Derived image | 12.1 GB |
| Cold scope acquire | 1.386 s |
| Warm first call | about 60 ms |
| Warm steady call | about 35 ms |
| Idle scope | 332.4 MiB RSS / 31 PIDs |
| Startup block I/O | 231 MB |

These values are comparison evidence, not a retained Docker gate or native SLA. P1–P5 must rerun same-host measurements and report methodology and raw sanitized output.

## 11. G0 Completion Record

- [x] Three source repositories/packages pinned by exact version, commit/tag, npm integrity, and license.
- [x] Complete source/test transplant maps recorded, including explicit optional/unsupported omissions.
- [x] `apply-seccomp` source, build process, published binary identities, runtime hash checks, and behavior verification locked.
- [x] Current Docker keep/adapt/delete/replace map recorded.
- [x] CodeGraph impact/affected evidence and its test-discovery limitation recorded.
- [x] O/S/L/M/P/R test IDs, target paths, commands, and host prerequisites frozen.
- [x] Current offline and Docker performance baselines recorded.

