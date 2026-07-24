# Plan: P3.1 — Agent engine extension runtime (isomorphic subset)

| Field | Value |
|-------|--------|
| **plan_id** | `P3.1-agent-engine-extensions` |
| **plan_version** | `0.2.3` |
| **status** | **completed** |
| **created** | 2026-07-24 |
| **updated** | 2026-07-24 |
| **roadmap** | [`docs/ROADMAP.md`](../ROADMAP.md) stage **P3.1** (`P3-extensions`) |
| **contract** | [`docs/contracts/ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.4** |
| **feature** | [`docs/features/agent_engine_extensions_v1.md`](../features/agent_engine_extensions_v1.md) **v0.2.2 frozen** — `agent-engine-extensions-v1` |
| **ADR** | [0006 local package subset](../contracts/adr/0006-package-manager-local-isomorphic-subset.md) · **[0008 extension runtime](../contracts/adr/0008-agent-engine-extensions-runtime.md)** |
| **depends_on** | **P3 done** — [`P3_capability_loader.md`](P3_capability_loader.md); feature frozen; ADR 0008 accepted; contract **v0.3.4** |
| **upstream** | `earendil-works/pi` **`main`** → `packages/coding-agent/src/core/extensions/**` (+ agent-session emit wiring) |
| **upstream_snapshot** | same pin as ai/agent/coding-agent — see [`UPSTREAM_SHA.txt`](UPSTREAM_SHA.txt) |
| **target** | `earendil_works.pi_agent.extensions` + Agent/harness emit + `package_manager` 收敛（AP3） |
| **tests** | Offline O1–O11；Live L1+L2+L3a+L3b+L4（L5 gate） |
| **non_goal** | Reasonix / pi-reasonix 业务包；TUI / install / npm / git / `~/.pi`；session 树 UX |

---

## 0. Purpose

1. **Port** coding-agent **extension 运行时**（`types` / `loader` / `runner` / `wrapper`）为 Python 同构，裁切为 **S-engine**（无 TUI）。
2. **Wire** feature §3.1 **IN** 事件到 Agent / harness loop emit（对照 upstream `agent-session` 次序）。
3. **AP3** 公开挂载符号与上游对齐；收敛 P3 临时 `CapabilityRegisterApi` / `apply_capability_report`，禁止与 runner **双 SoT**。
4. **M2** 现有 `echo_example` + search 三包 `register` 胶水改为 `registerTool`（业务 HTTP/normalize 不变）。
5. **SK2** skills/prompts 资源 load **且** apply 到 harness；**H1** 删除平行公共 host 钩子（`on_payload` / `transform_context`）。

**Approach:** isomorphic subset of `coding-agent/src/core/extensions/**` under `pi_agent.extensions` (feature **P-b** / ADR **D-EX2**). Not a greenfield hook brand; not full coding-agent product.

**Non-goals of this plan:**

| Out of scope | Why |
|--------------|-----|
| Reasonix / pi-reasonix 缓存业务包 | 另开 feature；本 plan 只交付钩子运行时 |
| coding-agent TUI / CLI / themes / `ui.*` | 产品 = agent 核心引擎（S-engine） |
| `project_trust` / `input` / `user_bash` / session 树事件 / `resources_discover` | feature §3.1 OUT |
| npm / git / `pi install` / `~/.pi` | ADR 0006 omit 不变 |
| 第二 agent 内核 / 独立 `packages/coding_agent` 空壳 | G3 / feature P-b |
| P4 `competitive_app` 业务 | R1 = P3.1，非 P4 |

---

## 1. Binding constraints (contract for implementers)

| ID | Must |
|----|------|
| Feature v0.2.0 | E2 / M2 / H1 / S-engine / C1 / AP3 / SK2 / O2 / §3.1–3.2 / §10 AC1 — **no inventing open scope** |
| ADR 0008 | D-EX1…D-EX6 |
| ADR 0006 / D5 / D22 | 本地 only；root `capability_packages/`；omit install/npm/git/home |
| D4 / G4 | 同构翻译；事件名 / dispatch / `registerTool` 对齐 upstream；不自创 Hook 品牌 |
| G3 | 落点 `earendil_works.pi_agent.extensions`；**非**第二内核 |
| G5 / G7 | Capability packages Python-only；packages ↛ `competitive_app` |
| G8 / R1 | Roadmap 阶段 **P3.1**；不得标 P4 业务完成 |
| A1 (docs) | ADR 0008 + 契约 0.3.4 **已落地**（实现前文档门） |
| M2 | **无** `add_tool` 长期兼容层 |
| H1 | loop **仅** extension 事件改 payload/context；删平行公共 host 钩子 |
| AP3 | 公开 API = `create_extension_runtime` / `load_extensions` / `ExtensionRunner` / `wrap_registered_tools`（snake_case 可，语义一一） |
| C1 | ExtensionContext 引擎字段 only；无 `ui`；未接线 IN 方法 **显式抛错** |

**Prerequisite check (gate G0):**

```bash
.venv/bin/pytest tests/packages/ai tests/packages/agent tests/capability_loader -m "not live" -q
```

P3 `echo_example` path + search offline suite remain green after each phase.

---

## 2. Upstream module map (port vs omit)

Re-fetch: `scripts/fetch_upstream.sh` sparse paths already include `packages/coding-agent` (see `UPSTREAM_SHA.txt`).  
Local mirror: `vendor/earendil-works-pi/packages/coding-agent/src/core/extensions/`.

Companion checklist: [`P3_1_module_map.md`](P3_1_module_map.md) (update as rows land).

### 2.1 Port (S-engine)

| Upstream | Python target (expected) | Responsibility |
|----------|--------------------------|----------------|
| `coding-agent/src/core/extensions/types.ts` | `pi_agent/extensions/types.py` | IN 事件 + results + C-engine `ExtensionContext` + `ExtensionAPI` 引擎子集 + runtime/extension shapes |
| `…/extensions/loader.ts` | `pi_agent/extensions/loader.py` | `create_extension_runtime` / `load_extensions` / factory load；**host-delta:** `.py` + importlib |
| `…/extensions/runner.ts` | `pi_agent/extensions/runner.py` | `ExtensionRunner`：bindCore、dispatch、result merge、`createContext` |
| `…/extensions/wrapper.ts` | `pi_agent/extensions/wrapper.py` | `wrap_registered_tool(s)` → `AgentTool` |
| `…/extensions/index.ts` | `pi_agent/extensions/__init__.py` | 公开 re-exports（AP3 面） |
| `coding-agent/src/core/agent-session.ts`（runner bind / emit 次序） | `agent.py` / `agent_loop.py` / harness | §3.1 IN emit 点；对照 `_handleAgentEvent` / `before_agent_start` / provider hooks |
| `coding-agent` package 资源加载中与 extension load 相关部分 | 演进现有 `package_manager/*` | E2：与 `load_extensions` 合流；install 仍 omit |

### 2.2 Explicit omit (must not ship in public API)

| Upstream | Status |
|----------|--------|
| `ExtensionUIContext` / `ui` / `hasUI` / theme / widgets / terminal input | **omit**（§3.2 OUT） |
| `project_trust` / `input` / `user_bash` events | **omit**（§3.1 OUT） |
| `session_before_switch` / `session_before_fork` / `session_before_tree` / `session_tree` | **omit** |
| `resources_discover` | **omit** |
| `ExtensionCommandContext` fork/switch/navigateTree/newSession/reload UX | **omit** |
| `registerCommand` / `registerShortcut` / `registerFlag` / message·entry renderers（TUI） | **omit** from public S-engine surface（除非实现期证明引擎必需 — 默认 omit） |
| `discoverAndLoadExtensions` 的 `~/.pi` / agentDir / npm 路径 | **omit**（ADR 0006） |
| `PackageManager.install*` / npm / git | **omit** |

Contract tests must fail if OUT events/`ui`/install helpers appear on public `on` / Context / package_manager install paths.

### 2.3 Host deltas (allowed)

| Upstream | Python / 本仓 |
|----------|----------------|
| `.ts` + jiti | `.py` + importlib（P3 已有） |
| `ToolDefinition` + wrapToolDefinition | Prefer `AgentTool` as registered definition when packages already produce tools；wrap 仍经 `wrap_registered_tools` |
| 完整 TUI SessionManager / ModelRegistry | 只读 session 视图 / 本仓等价 model 访问；未接线 → **raise** |
| `ExtensionMode` tui/rpc | 仅引擎占位（若保留）；无 UI 分支 |

### 2.4 Emit wiring map (§3.1 IN — all required for exit)

| Event | Host emit locus (expected) | Notes |
|-------|----------------------------|-------|
| `session_start` / `session_shutdown` / `session_info_changed` | harness / session open-close | |
| `session_before_compact` / `session_compact` | harness compaction path | result merge: cancel / compaction |
| `context` | Agent → loop `transformContext` 接线 | 改 messages |
| `before_provider_request` | Agent → stream `onPayload` 接线 | 可替换 payload |
| `before_provider_headers` | stream headers hook（若本仓有） | 原地改 headers |
| `after_provider_response` | stream `onResponse` 接线 | |
| `before_agent_start` | `Agent.prompt` 前 | 可改 systemPrompt |
| `agent_start` / `agent_end` / `agent_settled` | `_process_events` / idle settle | |
| `turn_start` / `turn_end` | `_process_events` | |
| `message_start` / `message_update` / `message_end` | `_process_events` | `message_end` 可替换同 role message |
| `tool_execution_start\|update\|end` | `_process_events` | 观测 |
| `tool_call` / `tool_result` | loop before/after tool | block / 改 result |
| `model_select` / `thinking_level_select` | Agent model/thinking setters | |

**Rule:** 不得以「分阶段 gap」跳过上表任一 IN 事件而不改 feature 契约。

### 2.5 Public surface checklist (AP3)

Must exist or be documented host-delta in module map:

- `create_extension_runtime`
- `load_extensions`（+ 可选 sync/cached 变体，若需要）
- `load_extension_from_factory`（测试/inline）
- `ExtensionRunner`（`bind_core` / `emit*` / `has_handlers` / `create_context` / `get_all_registered_tools`）
- `wrap_registered_tools` / `wrap_registered_tool`
- `ExtensionAPI.on`（仅 IN）+ `register_tool` / `registerTool`
- Attach path：runner 绑定 Agent + tools merge（收敛后的 apply / attach 符号，**单一 SoT**）

---

## 3. Target layout

```text
packages/agent/src/earendil_works/pi_agent/
  extensions/
    __init__.py                 # AP3 public re-exports
    types.py                    # IN events, C-engine Context, ExtensionAPI subset, runtime shapes
    loader.py                   # create_extension_runtime, load_extensions (.py)
    runner.py                   # ExtensionRunner dispatch + merge
    wrapper.py                  # wrap_registered_tools
  package_manager/              # evolve: call extensions.loader; converge apply (no dual SoT)
    extensions_loader.py        # thin delegate or retire CapabilityRegisterApi
    apply.py                    # attach runner + merge tools
    resource_loader.py          # E2 load path shared runtime
  agent.py                      # set_extension_runner; emit IN; H1 (no public on_payload/transform_context)
  agent_loop.py                 # keep core hooks as plumbing wired by Agent
  harness/
    agent_harness.py            # SK2 skills/prompts into system prompt; session/compact emit
    skills.py / prompt_templates.py / compaction/…

capability_packages/
  echo_example/extensions/*.py          # M2: registerTool
  search_tavily|anysearch|grok/…        # M2 glue only

docs/plans/
  P3_1_agent_engine_extensions.md       # this file
  P3_1_module_map.md                    # checklist (A2)

tests/
  packages/agent/
    unit/extensions/                    # runner merge, loader on/registerTool, OUT absent
    integration/faux/                   # emit + payload/systemPrompt observable
  capability_loader/
    unit|contract|integration/faux      # M2 search+echo; SK2 fixture; omit install
```

### 3.1 Extension host convention (Python)

Upstream loads `.ts` via jiti. **Host delta** (unchanged from P3 discovery):

1. **Preferred:** `extensions/**/*.py` exporting `register(api)`.
2. **Fallback:** `create_tools()` / `TOOLS` still accepted **only** if they call through `register_tool` path during load — prefer migrate to `register(api)`.

```python
def register(api) -> None:
    api.register_tool(  # or registerTool
        AgentTool(name="echo", description="…", parameters={…}, label="Echo", execute=…)
    )
    api.on("before_agent_start", on_before_start)
```

**M2:** 禁止新代码使用 `api.add_tool`；实现期删除 `CapabilityRegisterApi` 公共面（无兼容别名层）。

### 3.2 Attach path (normative AP3)

```python
from earendil_works.pi_agent.extensions import (
    create_extension_runtime,
    load_extensions,
    ExtensionRunner,
    wrap_registered_tools,
)

runtime = create_extension_runtime()
loaded = await load_extensions(paths, cwd=cwd, runtime=runtime)
runner = ExtensionRunner.from_load_result(loaded, cwd)
runner.bind_core(actions, context_actions)
tools = wrap_registered_tools(runner.get_all_registered_tools(), runner)
agent.set_extension_runner(runner)
# merge tools into agent.state.tools (first_wins default)
```

P3 convenience may remain as a **thin** wrapper that **only** calls the above (e.g. `apply_capability_report` becomes attach+merge, not a second SoT). Final state: runner owns handlers; tools come from `wrap_registered_tools`.

### 3.3 SK2 apply

- Package `skills/` / `prompts/` still discovered by `package_manager` (E2).
- After load, harness must **inject** skills into system prompt (existing `build_system_prompt(skills=…)`) and expose prompts to harness template surface.
- Do **not** invent `api.add_skill` as a parallel brand on `ExtensionAPI` if upstream uses package resources.

---

## 4. Status board (update as you go)

Status: `todo` | `in_progress` | `done` | `blocked`.

| Step | Phase | Status | Note |
|------|-------|--------|------|
| G0 | P1–P3 offline green | **done** | 119 passed baseline |
| D0 | ADR 0008 + contract 0.3.4 + roadmap P3.1 + feature freeze | **done** | docs gate |
| A1 | Scaffold `pi_agent/extensions/` + `upstream:` headers | **done** | |
| A2 | Write `P3_1_module_map.md` from §2 | **done** | closed with port statuses |
| A3 | types: IN events + C-engine Context + ExtensionAPI subset | **done** | OUT absent |
| A4 | loader: `create_extension_runtime` + `load_extensions` (.py) | **done** | |
| A5 | runner: dispatch + result merge + `create_context` | **done** | |
| A6 | wrapper: `wrap_registered_tools` | **done** | |
| B1 | Agent/harness emit every §3.1 IN (§2.4 map) | **done** | faux event-map coverage |
| B2 | AP3 public API；收敛 apply / 删除 `CapabilityRegisterApi` 双 SoT | **done** | |
| B3 | H1 remove public `on_payload` / `transform_context` | **done** | |
| B4 | SK2 skills/prompts apply to harness | **done** | |
| C1 | M2: echo + search 三包 → `registerTool` | **done** | business logic unchanged |
| C2 | Feature §10 Offline O1–O11（unit + faux + contract 高覆盖） | **done** | 124 passed, 24 deselected |
| C2L | Feature §10 Live L1+L2+L3a+L3b+L4（真模型；双钩子必过） | **done** | 24 passed；AnySearch + Grok real-model paths included |
| C3 | Sync search feature doc `add_tool` → `registerTool` | **done** | search feature v0.1.12 |
| C4 | Plan status completed；roadmap P3.1=done；module map closed | **done** | |

**Rules:**

- Do not start B1 until A3–A6 importable and unit-smokeable.
- Do not mark P3.1 done without **C2 + C2L**（feature §10 Offline + Live）。
- Do not implement Reasonix package in this plan.
- Do not restore install/npm/git/`~/.pi`.

---

## 5. Phased implementation steps

### Phase A — Scaffold & extension subsystem port

**A1. Scaffold**

1. Create `packages/agent/src/earendil_works/pi_agent/extensions/` tree (§3).
2. Every file header: `upstream: packages/coding-agent/src/core/extensions/<file>.ts`.
3. Empty modules importable: `import earendil_works.pi_agent.extensions`.
4. `codegraph sync` after files land.

**A2. Module map**

Generate/update `docs/plans/P3_1_module_map.md` with every §2.1–2.2 row → `todo|done|host-delta|omit`.

**A3. Types (S-engine only)**

Port IN event TypedDicts/dataclasses, result types, `IN_EVENTS` / `OUT_EVENTS` frozensets, `Extension` / `ExtensionRuntime` / `LoadExtensionsResult` / `RegisteredTool` / `SourceInfo`, C-engine Context protocol, `ExtensionAPI` with `on` + `register_tool` only (no ui methods).

**Tests:** OUT event registration raises or is rejected; `ui` not on public Context.

**A4. Loader**

- `create_extension_runtime()` — action stubs throw until `bind_core`.
- `load_extensions(paths, cwd, runtime?)` — importlib `.py`, call `register(api)`.
- `load_extension_from_factory` for tests.
- Reject `api.on(<OUT event>)`.

**Tests:** fixture extension registers tool + handler; load errors → diagnostics/errors list.

**A5. Runner**

Port:

- `bind_core` / context actions
- `has_handlers` / `on_error` / `emit_error`
- `emit` (generic)
- `emit_context` / `emit_before_provider_request` / `emit_before_provider_headers`
- `emit_before_agent_start` (chain systemPrompt)
- `emit_tool_call` / `emit_tool_result` / `emit_message_end`
- `session_before_compact` cancel merge via `emit`
- `create_context` (C1 raises if compact/etc. unwired — or wire minimal stubs that raise)

**Tests:** handler order; systemPrompt chain; tool_call block; payload replace.

**A6. Wrapper**

`wrap_registered_tools` → `AgentTool[]` usable by Agent loop.

**Exit A:** extensions package importable; unit tests for loader/runner/wrapper green; module map rows A3–A6 → done/host-delta.

---

### Phase B — Wire + converge

**B1. Emit §3.1 IN**

Wire Agent / harness per §2.4. Prefer:

- runner-backed `transformContext` / `onPayload` / tool hooks **inside** Agent when runner attached (loop plumbing stays agent-core isomorphic);
- `_process_events` mirrors upstream agent-session event fan-out;
- compaction path emits `session_before_compact` / `session_compact`.

**Tests:** integration fixture extension observes `agent_start` / `turn_*` / `message_*` / tool execution events.

**B2. AP3 converge**

1. Export AP3 symbols from `pi_agent.extensions` and package root as needed.
2. `package_manager` materialize uses shared `create_extension_runtime` + `load_extensions`.
3. `apply_capability_report` / attach: **single** path → `ExtensionRunner` + `wrap_registered_tools` + tool merge.
4. Remove public `CapabilityRegisterApi` / `add_tool` (M2).

**B3. H1**

- Remove public `AgentOptions.transform_context` / `on_payload` (and any documented host aliases for the same job).
- App customization = extension `api.on(...)` only.
- Contract/unit: attributes absent from public options.

**B4. SK2**

- Fixture package with `skills/` and/or `prompts/`.
- After load + harness construct, skills appear in system prompt (or harness-accessible list); prompts readable via harness surface.

**Exit B:** Agent with attached runner runs faux loop; payload or systemPrompt mutation observable; no dual SoT; H1 green.

---

### Phase C — Consumers + exit

**C1. M2 migrate packages**

| Package | Change |
|---------|--------|
| `echo_example` | `api.add_tool` → `api.register_tool` / `registerTool` |
| `search_tavily` / `search_anysearch` / `search_grok` | same glue only |

Business HTTP, normalize, env fail-closed, envelopes: **unchanged**.

**C2. Feature §10 Offline（高覆盖）**

Map tests 1:1 to feature §10.1–10.2（O1–O11）。优先：

- happy path 链路（register → wrap → Agent faux toolCall）；
- **边界**：OUT 拒绝、load 失败、handler 抛错、tool block、message_end 改 role 拒绝、未 bind 的 action 桩、invalidate/stale；
- multi-handler merge 顺序。

**C2L. Feature §10 Live（真实跑通 — 主路径）**

1. Fixture：**假 extension 包**——`registerTool` + `on("before_agent_start")` **与** `on("before_provider_request")`（同一包或两个 fixture 均可，但 L3a/L3b 都要真跑）。  
2. Load → AP3 attach → **真模型** Agent。  
3. **L1–L2**：tool 已注册；模型 **真实 toolCall**；**toolResult** 非空。  
4. **L3a 必过**：`before_agent_start` 改 systemPrompt，真请求后可观测。  
5. **L3b 必过**：`before_provider_request` 改/标记 payload，真请求后可观测（**不可**用「只测 tool 事件」代替）。  
6. **L4**：`echo_example`（或同构 capability 形状）真模型调 tool。  
7. 无密钥 → skip；有密钥 → L1+L2+L3a+L3b+L4 全绿。  
8. **不**要求 Live：§3.1 全表、block/merge 边界、SK2、search live、compact 产品环（Offline / 既有 suite）。

**C3. Docs**

- Bump `search_capability_packages_v1` text that still says `api.add_tool`.
- Close module map rows.

**C4. Closeout**

- This plan `status: completed`; bump `plan_version` if needed.
- Roadmap §5 **P3.1=done**.
- Offline suite green **and** live suite green（密钥齐全时）.

Public load path after converge (illustrative):

```python
report = await load_capability_packages(enabled=["echo_example"])
apply_capability_report(agent, report)  # attaches runner + tools; not a second SoT
# or explicit:
# attach_extension_runtime(agent, load_extensions_result, cwd=…)
```

---

## 6. Test strategy (prevent contract & isomorphism drift)

### 6.1 Offline（默认 CI，高覆盖）

| Layer | Assert | Feature §10 |
|-------|--------|-------------|
| Unit loader | `registerTool` + `on(IN)`；OUT 拒绝；坏路径 diagnostic | 1, 3, O6, O8 |
| Unit runner | systemPrompt 链；payload replace；tool block 短路；message_end；handler 抛错不崩 | O2, O3, O7, O9 |
| Unit runtime | 未 bind 抛错；invalidate/stale | O10 |
| Unit/contract AP3 | 符号存在；apply 非双 SoT；无 ui Context | 1, 4, O6 |
| Integration faux | registerTool → Agent toolResult；emit 可观测 | O1, O2 |
| Integration SK2 | fixture skills/prompts → harness | O4 |
| Contract H1 | 无公开 `on_payload` / `transform_context` | O5 |
| Contract omit | 无 install/npm/git/home；无 TUI 依赖 | O11 |
| Regression | search + echo offline 仍绿（M2） | O1 |

```bash
# offline (default CI)
.venv/bin/pytest tests/packages/ai tests/packages/agent tests/capability_loader -m "not live" -q

# focused offline
.venv/bin/pytest tests/packages/agent -k extension -m "not live" -q
.venv/bin/pytest tests/capability_loader -m "not live" -q
```

### 6.2 Live（exit 必过；无密钥 skip）

| Layer | Assert | Feature §10 |
|-------|--------|-------------|
| Live fixture load | 假 extension 包 `registerTool` 真实 import/load | L1 |
| Live Agent tool | 真模型 toolCall → toolResult 非空 | L2 |
| Live systemPrompt hook | `before_agent_start` 改 systemPrompt 真跑可观测 | **L3a 必过** |
| Live payload hook | `before_provider_request` 改/标记 payload 真跑可观测 | **L3b 必过** |
| Live capability shape | echo_example 或同构 package 路径 | L4 |
| Live gate | 无密钥 skip；有密钥 L1+L2+L3a+L3b+L4 全 pass | L5 |

**明确不要求 Live：** §3.1 全 IN 表、tool block / message_end 边界、multi-handler 顺序、H1/OUT/stale、SK2、search 三包 live、compact 全产品环（见 Offline O* / 既有 `test_live_compaction` / search live）。

```bash
# live (local / secret CI)
.venv/bin/pytest tests/packages/agent/integration/live -m live -q
# and/or
.venv/bin/pytest tests/capability_loader/integration/live -k extension -m live -q
```

Live env：沿用 `tests/live_env`（`OPENAI_API_KEY` / `MODEL_API_KEY` / model id / base URL）。**永不** log 密钥。

**P3.1 done 条件：** Offline §6.1 全绿 **且** 至少一次 Live §6.2（L1+L2+L3a+L3b+L4）在密钥齐全环境下全绿。


---

## 7. Risks

| Risk | Mitigation |
|------|------------|
| Emit 点遗漏 | §2.4 checklist in C2；对照 upstream `agent-session` |
| Context 字段本仓无等价物 | C1：未接线 **raise**；禁止静默 no-op |
| 双 SoT（apply vs runner） | AP3 + 删除/私有化旧 apply 语义；单一 attach 路径 |
| 范围胀到 TUI / session 树 | feature OUT + contract tests on public `on` |
| M2 破坏 search 三包 | 仅改 register 胶水；offline suite 为 gate |
| `ToolDefinition` vs `AgentTool` 阻抗 | host-delta document in module map；packages keep `AgentTool` |
| H1 破坏内部测试对 loop hooks 的依赖 | loop config 可保留 plumbing；**公开** AgentOptions 去掉 host 钩子 |

---

## 8. Definition of done

- [x] Feature §10 **Offline O1–O11** 全绿（高覆盖，含边界）
- [x] Feature §10 **Live L1+L2+L3a+L3b+L4** 在密钥齐全环境全绿（假 extension + 真模型 + 双钩子）
- [x] `P3_1_module_map.md` 每行 `done` / `host-delta` / `omit`（无悬空 `todo`）
- [x] ADR 0006 omit 仍成立（install/npm/git/home 不进公开路径）
- [x] Search 三包 + echo **M2** offline 绿
- [x] 无公开 `on_payload` / `transform_context`；无 `CapabilityRegisterApi.add_tool` 公共面
- [x] Roadmap **P3.1=done**；本 plan **completed**

---

## 9. Revision log

| Version | Date | Note |
|---------|------|------|
| 0.1.0 | 2026-07-24 | 初版：对齐 feature v0.2.0 + ADR 0008（精简板） |
| 0.2.0 | 2026-07-24 | **格式对齐** P3/P4：完整 binding / port·omit map / emit wiring / layout / 分步 Phase A–C / §10 测试矩阵 / DoD；增补 `P3_1_module_map.md` |
| 0.2.1 | 2026-07-24 | 验收 **AC1+**：Offline 高覆盖 O1–O11；Live L1–L5（假 extension + 真模型）；C2/C2L；对齐 feature **v0.2.1** |
| 0.2.2 | 2026-07-24 | Live 收紧 **L3a/L3b 均必过**；明确非 live 范围；对齐 feature **v0.2.2** |
| 0.2.3 | 2026-07-24 | 实现完成：Offline 124 passed；Live 24 passed；AP3/M2/H1/SK2 收敛；P3.1 done |
