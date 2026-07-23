# Plan: P2 — C-tier isomorphic port of `packages/agent`

| Field | Value |
|-------|--------|
| **plan_id** | `P2-packages-agent` |
| **plan_version** | `0.1.0` |
| **status** | **active** |
| **created** | 2026-07-22 |
| **roadmap** | [`docs/ROADMAP.md`](../ROADMAP.md) stage **P2** |
| **contract** | [`docs/contracts/ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.1** |
| **depends_on** | **P1 done** (`earendil_works.pi_ai`) — see [`P1_packages_ai.md`](P1_packages_ai.md) |
| **upstream** | https://github.com/earendil-works/pi **`main`** → `packages/agent/**` |
| **upstream_snapshot** | main `@ c55ae2faa5d850e0e4650bd573f7f241b10e2e0b` (re-fetch before coding) |
| **upstream_npm** | `@earendil-works/pi-agent-core` (observed `0.81.1` at snapshot) |
| **target** | `packages/agent/` → import `earendil_works.pi_agent` |
| **tests** | `tests/packages/agent/` |

---

## 0. Purpose of this plan

1. Give **serial, checkable steps** for C-tier port of main `packages/agent` (core + harness target surface).
2. Define **contract / isomorphism drift tests** so session, tool loop, and deps cannot drift.
3. Separate **scaffold** → **core agent loop** → **session/harness** → **exit smoke** so progress is honest.

**Non-goals of this plan:**

| Out of scope | Why |
|--------------|-----|
| P3 capability loader / `capability_packages/` discovery | Separate stage (D5/D22); only leave clean tool-registration APIs |
| P4 `competitive_app` / research DAG | App domain must not enter agent |
| coding-agent TUI / package-manager install | Product non-goal |
| Replacing `pi_ai` with LangChain | Forbidden |
| Permanent mock LLM inside agent | Must depend on real `earendil_works.pi_ai` (tests may use **faux** models) |

---

## 1. Binding constraints (contract for implementers)

| ID | Must |
|----|------|
| D3 | **C-tier**: main `packages/agent` **core + harness** target surface (not demo loop + reinvent session) |
| D4 | TS→Python **isomorphic** port — module boundaries + behavior |
| D14 | Align to **current main** |
| D16 / G8 | **After P1**; whole P2 before P3/P4 claims |
| D17 / D18 | Path `packages/agent/`; import **`earendil_works.pi_agent`** |
| D20 | **asyncio** public APIs (`prompt`, `wait_for_idle`, loop) |
| D21 | Tool args: TypeBox → **Pydantic / JSON Schema** validation timing aligned with main |
| D24 / D25 | Session SoT = **JSONL**; default dir **`data/sessions/`** (not /tmp-only) |
| G3 | Unique agent kernel = `packages/agent` |
| G4 / G9 | Mappable to main; no parallel self-invented agent tree |
| G7 | Import direction: `pi_agent` → `pi_ai` only; **↛** `competitive_app` / domain |
| — | **No** second agent framework |

**Prerequisite check (gate G0):** before Phase B, `import earendil_works.pi_ai` works; offline P1 suite still green.

---

## 2. Upstream module map (must remain mappable)

Re-fetch main before Phase B. Snapshot layout (informational).

### 2.1 Package role

Upstream: `@earendil-works/pi-agent-core`  
Depends on: `@earendil-works/pi-ai`  
Python: `earendil_works.pi_agent` → depends on `earendil_works.pi_ai`

### 2.2 Core (must port)

| Upstream | Python target (expected) | Responsibility |
|----------|--------------------------|----------------|
| `src/types.ts` | `types.py` | `StreamFn`, `AgentTool`, `AgentState`, `AgentEvent`, hooks, queue modes |
| `src/agent-loop.ts` | `agent_loop.py` | `agent_loop` / `agent_loop_continue` — LLM turn + tools |
| `src/agent.ts` | `agent.py` | `Agent` class: prompt/continue/subscribe/steering/follow-up/state |
| `src/stream-fn.ts` | `stream_fn.py` | Default stream fn injection |
| `src/proxy.ts` | `proxy.py` | Proxy helpers if still exported (host-adapt as needed) |
| `src/index.ts` | `__init__.py` | Public re-exports |

### 2.3 Harness (C-tier — required)

| Upstream | Python target | Responsibility |
|----------|---------------|----------------|
| `src/harness/agent-harness.ts` | `harness/agent_harness.py` | High-level harness: session + agent + resources |
| `src/harness/types.ts` | `harness/types.py` | Harness config/types |
| `src/harness/session/session.ts` | `harness/session/session.py` | Session tree / context build |
| `src/harness/session/jsonl-storage.ts` | `harness/session/jsonl_storage.py` | JSONL append/read |
| `src/harness/session/jsonl-repo.ts` | `harness/session/jsonl_repo.py` | Repo over storage |
| `src/harness/session/memory-storage.ts` | `harness/session/memory_storage.py` | In-memory backend (tests) |
| `src/harness/session/memory-repo.ts` | `harness/session/memory_repo.py` | |
| `src/harness/session/repo-utils.ts` | `harness/session/repo_utils.py` | |
| `src/harness/compaction/*` | `harness/compaction/*` | shouldCompact / summary / cut points / branch summary |
| `src/harness/skills.ts` | `harness/skills.py` | Skills resource loading semantics |
| `src/harness/system-prompt.ts` | `harness/system_prompt.py` | System prompt assembly |
| `src/harness/prompt-templates.ts` | `harness/prompt_templates.py` | Templates |
| `src/harness/messages.ts` | `harness/messages.py` | Message helpers |
| `src/harness/tools/*` | `harness/tools/*` | Built-in coding tools (read/write/edit/bash/…) |
| `src/harness/utils/*` | `harness/utils/*` | truncate, shell-output |
| `src/harness/env/nodejs.ts` | `harness/env/python.py` or host adapter | **Host delta**: Node env → Python stdlib |

### 2.4 Explicit host deltas / optional

| Upstream | Plan |
|----------|------|
| `src/node.ts` / node-only exports | Map to `earendil_works.pi_agent.node` host module or document omit |
| SQLite session package (`pi-storage-sqlite-node`) | **Not required for P2 exit** if JSONL path is complete; optional later |
| `ignore` / `diff` npm deps | Use Python equivalents (`pathspec`/`difflib`) |

### 2.5 Public surface checklist (from upstream `index.ts`)

Must exist or be documented as host-delta:

- `Agent`, `agent_loop` / `agent_loop_continue`
- `AgentHarness` (+ related harness types)
- Session: `Session`, JSONL storage/repo, memory storage/repo, context builders
- Compaction: `should_compact`, `compact`, `prepare_compaction`, branch summary helpers
- Skills / system prompt / prompt templates / messages
- Harness tools export surface
- `set_default_stream_fn` / stream defaults
- Types: `AgentEvent`, `AgentTool`, `AgentState`, `StreamFn`, queue/tool execution modes

### 2.6 Required capability families (roadmap — all required)

| Family | Upstream locus | P2 exit evidence |
|--------|----------------|------------------|
| Loop / agent / tools / events / abort | `agent.ts`, `agent-loop.ts` | tests: event order + tool + abort |
| Session tree | `harness/session/*` | tree build + branch |
| **JSONL @ `data/sessions/`** | jsonl-storage + default path config | write → re-open → resume |
| Compaction / branch | `harness/compaction/*` | unit + optional faux LLM summary |
| Skills / prompt resources | skills + system-prompt + templates | load + inject into context |
| Steering / follow-up | `Agent` queues | inject mid-run / after turn |
| Parallel vs sequential tools | loop + `AgentTool.executionMode` | concurrent finalize order vs source order |

---

## 3. Target repo layout after P2

```text
packages/agent/
  pyproject.toml                 # earendil-works-pi-agent; depends on earendil-works-pi-ai
  README.md
  src/earendil_works/pi_agent/
    __init__.py
    types.py
    agent.py
    agent_loop.py
    stream_fn.py
    proxy.py
    harness/
      agent_harness.py
      types.py
      messages.py
      skills.py
      system_prompt.py
      prompt_templates.py
      session/
        session.py
        jsonl_storage.py
        jsonl_repo.py
        memory_storage.py
        memory_repo.py
        repo_utils.py
      compaction/
        compaction.py
        branch_summarization.py
        utils.py
      tools/
        __init__.py
        read.py write.py edit.py bash.py ...
        tool_context.py
      utils/
        truncate.py
        shell_output.py
      env/
        python_env.py            # host adapter for nodejs.ts
tests/packages/agent/
  contract/                      # layout, imports, no domain leak, JSONL path
  unit/
  integration/
    faux/                        # agent + pi_ai faux models + fake tools
    session/                     # JSONL resume under tmp or data/sessions test dir
docs/plans/P2_module_map.md      # generated checklist (A3)
```

Root workspace: add `packages/agent` to uv/workspace members; pytest path already covers `tests/`.

**Default session path:**  
`Session` / harness config default `sessions_dir = <repo_or_cwd>/data/sessions` (or explicit inject). Tests use tmp_path; production default must **not** be ephemeral OS temp as sole SoT (D25).

---

## 4. Status board (update as you go)

Status: `todo` | `in_progress` | `done` | `blocked`.

| Step | Phase | Status | Owner note |
|------|-------|--------|------------|
| G0 | Verify P1 import + offline suite still green | done | 33 ai + agent scaffold offline green |
| A1 | Scaffold `packages/agent` pyproject + package tree | done | earendil_works.pi_agent importable |
| A2 | Pin upstream agent tree + SHA note | done | vendor sparse ai+agent @ c55ae2fa… |
| A3 | Write `docs/plans/P2_module_map.md` | done | |
| B0 | Types + StreamFn contract + AgentEvent | done | types.py + stream_fn + unit tests |
| B1 | `agent_loop` / continue (text only, no tools) | done | faux text event-order test |
| B2 | Tool execution sequential + parallel + hooks | done | echo/block/parallel source order |
| B3 | `Agent` class: prompt/continue/subscribe/state/abort | todo | |
| B4 | Steering + follow-up queues | todo | |
| B5 | Memory session storage/repo | todo | |
| B6 | **JSONL** storage/repo + default `data/sessions/` | todo | |
| B7 | Session tree context build / branch helpers | todo | |
| B8 | Compaction core (should/cut/summary interfaces) | todo | |
| B9 | Skills + system prompt + prompt templates | todo | |
| B10 | AgentHarness wiring | todo | |
| B11 | Built-in harness tools (minimal set first, then full map) | todo | |
| B12 | Host env adapter (Python) | todo | |
| C0 | Contract-drift tests green | todo | |
| C1 | Integration: prompt→tool→JSONL→resume green | todo | **exit smoke** |
| C2 | Module map closed; no competitive_app imports | todo | |
| C3 | Roadmap §5 P2=done; plan completed | todo | |

**Rules:**

- Do not start B5+ until B0–B3 green (loop+Agent solid).
- Do not mark P2 done without **C1** (JSONL resume smoke).
- Do not implement P3 loader inside this plan except leaving stable `AgentTool` registration API.

---

## 5. Phased implementation steps

### Phase A — Scaffold & pin

**A1. Scaffold**

1. `packages/agent/pyproject.toml`: name `earendil-works-pi-agent`, `depends on earendil-works-pi-ai`, python ≥3.12, pydantic, anyio.
2. Package layout §3; empty modules importable.
3. Root workspace member + editable install.
4. `tests/packages/agent/conftest.py` (path + fixtures: tmp sessions dir).
5. `codegraph index -f` after files land.

**A2. Upstream pin**

- Sparse checkout `packages/agent` into `vendor/` (or extend `scripts/fetch_upstream_ai.sh` → `fetch_upstream.sh`).
- Record SHA in `docs/plans/UPSTREAM_SHA.txt` (append agent line).

**A3. Module map**

Generate `docs/plans/P2_module_map.md` with every row in §2 → status `todo|done|host-delta`.

**Exit A:** `import earendil_works.pi_agent` succeeds; map committed.

---

### Phase B — Port

#### B0 — Types

Port `StreamFn`, `AgentTool`, `AgentState`, `AgentEvent` union, hook contexts, `ToolExecutionMode`, `QueueMode`, `AgentLoopConfig`.

**Tests:** event TypedDict shape smoke; tool schema validation helper.

#### B1 — Agent loop (text)

Port loop with:

- `agent_start` / `turn_start` / message events / `turn_end` / `agent_end`
- `convert_to_llm` + optional `transform_context`
- stream via `StreamFn` (use `models.stream_simple` + **faux**)
- failures encoded in stream (not throw) — align with pi_ai contract

**Tests:** faux assistant text-only; event order matches README sequence.

#### B2 — Tools

- Register `AgentTool` with execute callback + JSON schema params
- Validate args before execute (fail → error toolResult)
- `before_tool_call` / `after_tool_call`
- sequential vs parallel batch semantics (source order of toolResults)
- `terminate` early-stop when all tools in batch request it
- abort signal cancels in-flight work where feasible

**Tests:** fake `echo` / `add` tools; blocked tool; parallel two tools.

#### B3 — Agent class

Port:

- `prompt` (str | message | images)
- `continue_`
- `subscribe` (awaited, registration order)
- `wait_for_idle` / settlement after `agent_end` listeners
- state accessors (copy-on-assign for tools/messages arrays)
- `reset`, model/tools/thinking updates
- abort API

**Tests:** subscribe sees text deltas; state.messages grow; idle after prompt.

#### B4 — Steering / follow-up

Port queues + `steeringMode` / `followUpMode` (`all` | `one-at-a-time`).

**Tests:** inject steering mid-run (or between turns with slow faux); follow-up after agent_end path per upstream semantics.

#### B5–B7 — Session

1. Memory storage/repo (unit).
2. JSONL storage: append-only entries, load path, corruption policy (document).
3. Default path: `data/sessions/<session_id>.jsonl` (or directory layout matching upstream — **map exactly** once jsonl-storage is read).
4. Session tree: build context from leaf path; branch preparation hooks.

**Tests:**

- write N entries → new process/instance load → same context
- branch creates new leaf without destroying parent history
- default root resolves under `data/sessions` when not overridden

#### B8 — Compaction

Port thresholds + cut-point + summary interfaces. Summary generation may call `StreamFn` (faux in tests).

**Tests:** `should_compact` true/false; cut index stable; prepare does not drop required tool pairs incorrectly (mirror upstream tests intent).

#### B9 — Skills / prompts

Port skills discovery **semantics** for paths supplied by caller (full disk auto-scan of home is **not** P2 product requirement — only APIs that main agent exposes for resource loading). System prompt assembly + templates.

**Tests:** skill file → context injection string; template render.

#### B10 — AgentHarness

Wire Agent + Session + tools + streamFn into one façade matching upstream.

**Tests:** harness prompt persists to JSONL automatically.

#### B11 — Built-in tools

Port map for: `read`, `write`, `edit`, `bash`, `image`, path utils, mutation queue.  
**Priority:** read/write first (enough for smoke); rest for module map closeout.

**Tests:** tmp workspace read/write roundtrip; edit applies; bash optional/skip on policy.

#### B12 — Host env

Replace `harness/env/nodejs.ts` with Python path/cwd/env helpers.

**Exit B:** module map rows `done` or `host-delta`; package import stable.

---

### Phase C — Hardening & exit

1. Full `tests/packages/agent` offline green.
2. **Exit smoke (mandatory):**

```text
create Models + faux (or live optional)
create Agent/Harness with echo tool
prompt → tool call → toolResult → final text
JSONL written under data/sessions (or configured test root)
new Agent/Harness resume same session id
context contains prior turns; continue or second prompt works
```

3. Contract suite §6 green.
4. `codegraph explore "Agent agent_loop Session"` finds symbols.
5. Roadmap §5: P2 → `done`; this plan → `completed`.

**P2 exit criteria (roadmap — all required):**

| # | Criterion | Evidence |
|---|-----------|----------|
| 1 | Depends on real `earendil_works.pi_ai` | import-linter / contract test |
| 2 | JSONL session recoverable | C1 smoke |
| 3 | Tool validation timing aligned | unit + tool error path |
| 4 | tests cover loop+tool+session | `tests/packages/agent` |
| 5 | No competitive domain leak | contract ast scan |
| — | Exit smoke prompt→tool→JSONL→resume | C1 |

---

## 6. Test strategy (prevent contract & isomorphism drift)

### 6.1 Layers

| Layer | Path | CI |
|-------|------|-----|
| Contract / drift | `tests/packages/agent/contract/` | **always** |
| Unit | `tests/packages/agent/unit/` | always |
| Faux integration | `tests/packages/agent/integration/faux/` | always |
| Session/JSONL | `tests/packages/agent/integration/session/` | always |
| Live LLM | `tests/packages/agent/integration/live/` | optional, env-gated |

Default: `pytest tests/packages/agent -m "not live"`.

### 6.2 Contract tests (required)

#### C-LAYOUT

| Test id | Asserts |
|---------|---------|
| `test_packages_agent_path_exists` | `packages/agent/src/earendil_works/pi_agent` |
| `test_import_earendil_works_pi_agent` | import succeeds |
| `test_agent_depends_on_pi_ai` | package metadata / import graph includes pi_ai |
| `test_no_parallel_kernel_package` | no `packages/pi_core` agent clone |

#### C-DEPS / BOUNDARY

| Test id | Asserts |
|---------|---------|
| `test_no_forbidden_agent_frameworks` | no langchain / langgraph / crewai / autogen / semantic_kernel under pi_agent |
| `test_agent_does_not_import_competitive_app` | AST scan |
| `test_agent_does_not_import_capability_packages` | AST scan (P3 will load *into* agent, not reverse import) |
| `test_public_prompt_apis_are_async` | `Agent.prompt` / `wait_for_idle` coroutine |

#### C-SESSION

| Test id | Asserts |
|---------|---------|
| `test_default_sessions_root_is_data_sessions` | default config path ends with `data/sessions` (or documented relative) |
| `test_jsonl_roundtrip_resume` | write/load equality for entries |
| `test_jsonl_not_required_on_import` | import agent without creating sessions |

#### C-PUBLIC-API

| Test id | Asserts |
|---------|---------|
| `test_public_symbols_minimum_set` | `Agent`, `agent_loop`, `Session`, JSONL types, `AgentTool`, key events |
| `test_stream_fn_uses_pi_ai_shapes` | StreamFn accepts Model/Context from pi_ai |

### 6.3 Behavioral tests (required)

| Theme | Asserts |
|-------|---------|
| Event order text | README `prompt()` sequence |
| Event order tools | tool_execution_* + toolResult + second turn |
| complete/settle | `wait_for_idle` after agent_end listeners |
| Abort | mid-stream abort → stable state |
| Tool validation | bad args → error toolResult, no execute |
| beforeToolCall block | blocked reason text |
| Parallel tools | results source order preserved |
| Steering/follow-up | queue drains per mode |
| Compaction | shouldCompact + cut safety |
| Harness smoke | prompt persists + reload |

### 6.4 Mapping upstream tests → pytest (intent, not filename)

| Upstream | Python home |
|----------|-------------|
| `agent-loop.test.ts` | unit/integration faux |
| `agent.test.ts` | integration/faux |
| `harness/session.test.ts` | integration/session |
| `harness/storage.test.ts` / `repo.test.ts` | unit + session |
| `harness/compaction.test.ts` | unit |
| `harness/agent-harness*.test.ts` | integration |
| `harness/tools.test.ts` | unit/tools |
| `harness/skills.test.ts` / system-prompt / templates | unit |
| `e2e.test.ts` | integration (faux); live optional |

### 6.5 Live (optional, not exit-blocking)

`@pytest.mark.live` with `.env` gateway (see `scripts/smoke_live_model.py` pattern): Agent + real model + echo tool.  
P2 **exit does not require** live keys if faux+JSONL smoke is solid.

---

## 7. Intentional host-only deltas (allow-list)

| Delta | Reason | Mitigation |
|-------|--------|------------|
| TypeBox → Pydantic/JSON Schema | runtime | validation tests |
| Node streams/fs → asyncio + pathlib | runtime | behavior tests |
| `harness/env/nodejs` → Python env | no Node | `python_env.py` |
| SQLite node package | optional separate | JSONL is SoT for P2 |
| `diff` / `ignore` crates | npm → Python | difflib / pathspec |
| Coding tools that assume POSIX shell | CI OS | skip markers |

**Not allowed as host delta:** dropping JSONL; inventing second session SoT as default; inlining competitive research stages into agent; skipping tool event protocol.

---

## 8. Progress hygiene

1. One status-board row `in_progress` at a time for writers.
2. Module map row before new files.
3. Prefer **faux** `pi_ai` for all default tests.
4. No P3 loader / P4 domain code in P2 PRs.
5. Re-fetch main agent tree each major wave; update map if upstream moved.
6. PR title prefix: `P2:` + board step ids (e.g. `P2: B6 JSONL session`).
7. After large moves: `codegraph sync`.

---

## 9. Definition of Done (P2)

All true:

1. §4 board G0–C3 = `done`.
2. Roadmap exit criteria satisfied with linked evidence.
3. Contract §6.2 green offline.
4. Exit smoke: **prompt → tool → JSONL → resume** green.
5. `earendil_works.pi_agent` is the only agent kernel; depends on `earendil_works.pi_ai`.
6. Plan status `completed`; roadmap P2 = `done`.
7. **No** claim that capability loader or competitive_app is ready.

---

## 10. Immediate next actions (when starting implementation)

1. Run G0: `.venv/bin/pytest tests/packages/ai -m "not live" -q`.
2. A1 scaffold `packages/agent` + workspace wire.
3. A2–A3 fetch agent tree + module map.
4. B0–B3 loop+Agent with faux until event/tool tests green.
5. B6 JSONL early enough that C1 is not a late surprise.

Do **not** open P3/P4 implementation tracks in the same PR series without explicit dual-track approval.

---

## 11. Relationship to P3/P4 (boundary reminder)

```text
P2 delivers: Agent + tools API + Session JSONL + harness
P3 adds:     load capability_packages/* → register AgentTool(s)
P4 adds:     FastAPI/DDD/workflow calling AgentHarness
```

P2 must expose clean registration (`agent.state.tools = [...]` / harness tool lists) so P3 does not fork the kernel.

---

## 12. Revision log

| Version | Date | Note |
|---------|------|------|
| 0.1.0 | 2026-07-22 | Initial P2 plan: C-tier core+harness map, phased board, contract/JSONL exit smoke, host-delta allow-list. Upstream SHA `c55ae2fa…`. |
