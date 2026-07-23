# Plan: P3 — Local capability package loader

| Field | Value |
|-------|--------|
| **plan_id** | `P3-capability-loader` |
| **plan_version** | `0.1.0` |
| **status** | **active** |
| **created** | 2026-07-23 |
| **roadmap** | [`docs/ROADMAP.md`](../ROADMAP.md) stage **P3** |
| **contract** | [`docs/contracts/ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.1** |
| **ADR** | [`docs/contracts/adr/0004-local-capability-packages-only.md`](../contracts/adr/0004-local-capability-packages-only.md) |
| **depends_on** | **P2 done** (`earendil_works.pi_agent` — loop/tools/session/JSONL) — see [`P2_packages_agent.md`](P2_packages_agent.md) |
| **upstream** | *Not* a full coding-agent package-manager port. Tool **runtime** semantics stay in P2 agent; only **local discovery/registration** is new. |
| **target** | Loader module + repo root `capability_packages/` convention |
| **tests** | `tests/capability_loader/` (+ optional live under `tests/capability_loader/live/`) |

---

## 0. Purpose of this plan

1. Deliver **serial, checkable steps** for the local capability loader (contract §3.4 / §5 / D5 / D22).
2. Freeze the **subpackage directory convention + register API** so P4 can load tools without forking the agent kernel.
3. Ship **at least one example package** (echo/no-op is enough for exit; search/fetch can be stubs) that a real `Agent` can call.
4. Keep failure modes **observable and process-safe** (bad package must not kill the host).

**Non-goals of this plan:**

| Out of scope | Why |
|--------------|-----|
| npm / git / HTTP **download** or `pi install` CLI | D5 / D22 / G10; ADR 0004 |
| Scan `~/.pi`, user home, global agent dirs | Explicitly rejected |
| Full coding-agent package-manager / lockfile / marketplace | Product non-goal |
| P4 `competitive_app` / research DAG / FastAPI routes | Separate stage |
| Putting competitive **domain** types into capability packages | G7 / layering |
| Changing `packages/ai` or inventing a second agent framework | Kernel is P2 |
| Full-provider live matrix | P1 already limited; P3 live optional on gateway only |

---

## 1. Binding constraints (contract for implementers)

| ID | Must |
|----|------|
| D5 | Capabilities = **local directory load** of Python packages (tools / optional skills·prompts) |
| D6 | Package tools/extensions are **Python** (no nested Node for packages) |
| D16 / G8 | **After P2**; whole P3 before P4 claims |
| D21 | Tool args still validated by agent (Pydantic / JSON Schema timing from P2) |
| D22 | Root = **`capability_packages/`** only |
| G3 | Unique agent kernel remains `packages/agent` |
| G5 | Capability packages are Python-only and **only** from `capability_packages/` |
| G7 | `capability_packages/*` → register into agent; **↛** `competitive_app.domain` |
| G10 | **No** remote package download as default path |
| — | Import direction: loader may depend on `earendil_works.pi_agent` (types/AgentTool); packages depend on public `AgentTool` API only |

**Prerequisite check (gate G0):**

```bash
.venv/bin/pytest tests/packages/ai tests/packages/agent -m "not live" -q
# expect green (P1+P2 offline suite)
python -c "from earendil_works.pi_agent import Agent, AgentTool; print('ok')"
```

---

## 2. Design decisions (freeze for P3; ADR only if changed)

### 2.1 Where the loader lives

| Option | Choice for P3 |
|--------|----------------|
| A. Inside `packages/agent` as isomorphic extension | Avoid if it invents parallel “package-manager” tree |
| **B. Thin module under agent package** | **Chosen default:** `earendil_works.pi_agent.capability_loader` (or `local_packages`) — thin, not a second kernel |
| C. Separate `packages/local_package_loader/` | Allowed only if B blurs agent isomorphism; document non-upstream |

**Decision (P3):** implement under  
`packages/agent/src/earendil_works/pi_agent/capability_loader/`  
with public re-exports from `earendil_works.pi_agent` **or** explicit  
`from earendil_works.pi_agent.capability_loader import load_capability_packages`.

Module map row in `docs/plans/P3_module_map.md` (generate in A2).

### 2.2 Root path resolution

| Rule | Value |
|------|--------|
| Default root | `<repo_root>/capability_packages` |
| Override | constructor / function arg `root: Path` (tests use `tmp_path`) |
| Repo root discovery | explicit inject preferred; optional walk for `.git` / pyproject **only if documented** — tests always inject |
| Symlinks | resolve once; refuse escaping outside root (optional harden) |

### 2.3 Subpackage validity

A child of `capability_packages/` is a **candidate package** iff:

1. It is a **directory** (not a file).
2. Name does **not** start with `.` or `_` (skip `__pycache__`, `.gitkeep` dirs policy: empty skip).
3. It exposes a **register entry** (see §2.4).

Invalid / unloadable packages → recorded in load report; **do not** raise to kill the process unless `strict=True`.

### 2.4 Entry convention (minimal)

Support **one primary** entry (implement in order):

| Priority | Entry | Contract |
|----------|-------|----------|
| **1 (required)** | `<pkg>/register.py` **or** `<pkg>/__init__.py` | callable `register(api: CapabilityRegisterApi) -> None` |
| 2 (fallback) | `<pkg>/main.py` | same `register(api)` |
| Optional | `<pkg>/package.toml` / `manifest.json` | **optional** metadata only in P3 (`name`, `version`, `enabled`); **no** download fields |

**`CapabilityRegisterApi` (minimal surface):**

```python
class CapabilityRegisterApi(Protocol):
    def add_tool(self, tool: AgentTool) -> None: ...
    def add_skill(self, skill: Skill) -> None: ...          # optional use in P3
    def add_prompt_template(self, template: PromptTemplate) -> None: ...  # optional
    @property
    def package_name(self) -> str: ...
    @property
    def package_path(self) -> Path: ...
```

Packages **must not** import `competitive_app`.  
Packages **may** import `earendil_works.pi_agent.AgentTool` / types only.

### 2.5 Load result / observability

```python
@dataclass
class PackageLoadResult:
    name: str
    path: Path
    status: Literal["loaded", "skipped", "failed"]
    tools: list[str]          # tool names registered
    skills: list[str]
    error: str | None         # message if failed/skipped reason
```

```python
@dataclass
class LoadReport:
    root: Path
    results: list[PackageLoadResult]
    tools: list[AgentTool]
    skills: list[Skill]
    prompt_templates: list[PromptTemplate]

    @property
    def ok(self) -> bool: ...           # no hard failures if not strict
    @property
    def failed(self) -> list[PackageLoadResult]: ...
```

Logging: one line per package (`loaded N tools` / `failed: ImportError: ...`). Never log secrets.

### 2.6 Registration into Agent

Loader **returns tools**; wiring is caller-owned:

```python
report = load_capability_packages(root)
agent.state.tools = [*agent.state.tools, *report.tools]
# or AgentHarness(..., tools=report.tools)
```

Optional helper:

```python
apply_capability_report(agent: Agent, report: LoadReport, *, replace: bool = False) -> None
```

P3 **does not** auto-start an Agent; it only loads + can apply.

### 2.7 Enable policy

| Mode | Behavior |
|------|----------|
| **default** | Load **all** valid subdirs under root |
| optional | `enabled: list[str] \| None` whitelist of package **directory names** |
| optional | `disabled: list[str]` denylist |
| `strict: bool = False` | if True, first failure raises `CapabilityLoadError` after partial report |

Settings file for P4 can later map to `enabled`; P3 accepts kwargs / simple dict config only.

### 2.8 Isolation / import safety

| Rule | Implementation note |
|------|---------------------|
| Import path | Add package dir or synthetic namespace `capability_packages.<name>` via `importlib` |
| Prefer | `importlib.util.spec_from_file_location` for `register.py` to avoid polluting global `sys.modules` clashes |
| Name collisions | Two packages registering same `AgentTool.name` → **last wins + warning** (document); test asserts warning/report |
| Domain leak | Contract test: AST scan `capability_packages/**` for `competitive_app` imports |

---

## 3. Target layout after P3

```text
capability_packages/
  .gitkeep
  echo_example/                 # exit-smoke example (required)
    __init__.py                 # re-export or thin
    register.py                 # register(api)
    tools.py                    # echo AgentTool
    README.md                   # optional short usage
  # optional second example (recommended but not exit-blocking):
  # noop_broken/ used only in tests as fixture under tests/.../fixtures/

packages/agent/src/earendil_works/pi_agent/
  capability_loader/
    __init__.py                 # public API
    types.py                    # LoadReport, PackageLoadResult, CapabilityRegisterApi
    discover.py                 # list candidate dirs
    load.py                     # import + register
    apply.py                    # apply_capability_report(agent, report)
    errors.py                   # CapabilityLoadError

tests/capability_loader/
  contract/
    test_layout.py              # root name, no remote APIs, no competitive imports
    test_deps.py
  unit/
    test_discover.py
    test_load_success.py
    test_load_failure_isolated.py
    test_whitelist.py
    test_tool_name_collision.py
  integration/
    faux/
      test_agent_calls_capability_tool.py   # faux model + echo_example
    session/                                # optional: load + JSONL
  fixtures/
    good_echo/
    bad_syntax/
    bad_no_register/
    imports_domain/                         # for contract rejection if we scan fixtures only

docs/plans/P3_module_map.md
docs/plans/P3_capability_loader.md          # this plan
```

**Do not** put loader under `competitive_app/`.  
**Do not** require capability packages to be installable wheels in P3 (path import is enough).

---

## 4. Status board (update as you go)

Status: `todo` | `in_progress` | `done` | `blocked`.

| Step | Phase | Status | Owner note |
|------|-------|--------|------------|
| G0 | P1+P2 offline suite still green; `pi_agent` importable | todo | |
| A1 | Scaffold `capability_loader/` package + empty `capability_packages/` | todo | |
| A2 | Write `docs/plans/P3_module_map.md` | todo | |
| A3 | Document subpackage convention (README under `capability_packages/`) | todo | short |
| B1 | `discover` candidates + LoadReport types | todo | |
| B2 | `load` single package (`register(api)`) | todo | |
| B3 | Multi-package load + failure isolation + whitelist/denylist | todo | |
| B4 | `apply_capability_report` → `Agent.state.tools` | todo | |
| B5 | Example package `echo_example` | todo | |
| B6 | Optional: skills/prompt registration path | todo | can be thin |
| C0 | Contract tests (layout, no remote, no domain import) | todo | |
| C1 | Integration: load echo → Agent(faux) → tool call | todo | **exit smoke** |
| C2 | Optional live: load echo → real gateway tool call | todo | env-gated |
| C3 | Module map closed; roadmap P3=done; plan completed | todo | |

**Rules:**

- Do not mark P3 done without **C1** (echo tool via loader + agent).
- Do not implement downloaders “for later” inside this plan.
- Do not put research/business tools that need App domain into the example package.

---

## 5. Phased implementation steps

### Phase A — Scaffold & docs

**A1. Scaffold**

1. Create `packages/agent/.../capability_loader/` modules (importable stubs).
2. Create `capability_packages/.gitkeep` (+ later `echo_example`).
3. Export public symbols from loader `__init__.py`.
4. Tests skeleton under `tests/capability_loader/`.
5. `codegraph index -f` after files land.

**A2. Module map**

Generate `docs/plans/P3_module_map.md` with rows for each loader file + example package + status.

**A3. Human convention doc**

Short `capability_packages/README.md`:

- how to add a package
- `register(api)` signature
- enabled/disabled policy
- link to this plan + ADR 0004

**Exit A:** `from earendil_works.pi_agent.capability_loader import load_capability_packages` works (may return empty).

---

### Phase B — Implement loader

#### B1 — Discover

- `list_capability_package_dirs(root) -> list[Path]`
- skip non-dirs, hidden, empty placeholders as documented

**Tests:** tmp tree with mix of valid/invalid names.

#### B2 — Load one package

- Resolve entry module (`register.py` → `__init__.py` → `main.py`)
- Build `CapabilityRegisterApi` collecting tools/skills/templates
- Call `register(api)`
- Capture exceptions → `PackageLoadResult(status="failed", error=...)`

**Tests:** fixture `good_echo` loads 1 tool; `bad_syntax` fails; `bad_no_register` skipped/failed with clear error.

#### B3 — Multi load + policy

- Iterate candidates sorted by name (stable)
- `enabled` / `disabled` filters
- `strict` mode
- tool name collision policy (warn + last wins)

**Tests:** whitelist loads subset; one bad package does not block others when `strict=False`.

#### B4 — Apply to Agent

- `apply_capability_report(agent, report, replace=False)`
- copy-on-assign tools list (P2 Agent semantics)

**Tests:** agent tools length increases; replace=True swaps.

#### B5 — Example `capability_packages/echo_example`

```python
# register.py
def register(api):
    api.add_tool(create_echo_tool())
```

Echo tool: args `{ "text": string }` → content text. Same spirit as P2 live echo.

**Tests:** integration loads **repo** `echo_example` (or test copy) and runs faux Agent.

#### B6 — Optional skills/prompts

If cheap: `api.add_skill` / `add_prompt_template` + load resource files under package `skills/` / `prompts/`.  
If timeboxed: leave API methods raising `NotImplementedError` **or** no-op with report field empty — document in module map as partial.

**P3 exit does not require** skills files if tools path is solid; B6 is best-effort.

**Exit B:** load report + apply API stable; echo_example present.

---

### Phase C — Hardening & exit

#### C0 — Contract / anti-drift

| Test | Assert |
|------|--------|
| Layout | `capability_packages/` exists at repo root |
| Loader path | `earendil_works.pi_agent.capability_loader` importable |
| No remote | loader source has no `git clone` / `pip install` / `httpx.get` for packages (allowlist stdlib + pi_agent) |
| No domain | capability_packages + loader ↛ `competitive_app` |
| Kernel intact | P1+P2 offline suite still green |

#### C1 — Exit smoke (mandatory)

```text
load_capability_packages(root) 
  → report.tools contains "echo" (or echo_example tool name)
  → Agent(faux, tools=report.tools)
  → prompt forces tool call
  → toolResult present / non-error
```

Optional: persist messages to JSONL (P2) — nice-to-have, not required for P3 exit.

#### C2 — Optional live

`@pytest.mark.live` under `tests/capability_loader/live/`:

- load `echo_example`
- Agent + gateway from `.env` (reuse `tests/live_env.py`)
- model must call echo once

Skip without keys. **Not exit-blocking.**

#### C3 — Closeout

1. `P3_module_map.md` rows `done` / `host-delta` / `deferred`.
2. Roadmap §5: P3=`done`; P4 unblocked.
3. This plan `status=completed`, bump `plan_version`.
4. `agents.md` points next work to P4 plan (when written).

**Exit C:** C0+C1 green + docs updated → **P3=done**.

---

## 6. Public API sketch (normative for implementers)

```python
# earendil_works.pi_agent.capability_loader

def load_capability_packages(
    root: Path | str | None = None,
    *,
    enabled: list[str] | None = None,
    disabled: list[str] | None = None,
    strict: bool = False,
) -> LoadReport:
    """Discover and load packages under root (default: <cwd or injected>/capability_packages)."""

def apply_capability_report(
    agent: Agent,
    report: LoadReport,
    *,
    replace: bool = False,
) -> None:
    """Merge or replace agent.state.tools with report.tools; optionally extend skills later."""

class CapabilityLoadError(Exception):
    """Raised when strict=True and any package fails (carries LoadReport)."""
```

CamelCase aliases optional for TS familiarity — **not required** in P3.

---

## 7. Test strategy

| Layer | Path | Default CI |
|-------|------|------------|
| Contract | `tests/capability_loader/contract/` | always |
| Unit | `tests/capability_loader/unit/` | always |
| Integration faux | `tests/capability_loader/integration/faux/` | always |
| Live | `tests/capability_loader/live/` | optional `-m live` |
| Regression | `tests/packages/ai` + `tests/packages/agent` `-m "not live"` | always on P3 PR |

Commands:

```bash
# offline gate
.venv/bin/pytest tests/packages/ai tests/packages/agent tests/capability_loader -m "not live" -q

# P3 only
.venv/bin/pytest tests/capability_loader -m "not live" -q

# optional live
.venv/bin/pytest tests/capability_loader -m live -v
```

---

## 8. Relationship to P2 / P4

```text
P2 delivered: Agent + AgentTool + session JSONL + harness
P3 delivers:  discover/load capability_packages → AgentTool[] (+ optional skills)
P4 will:      FastAPI wiring calls loader at startup; workflow uses Agent+tools
```

P4 must **not** reimplement discovery. It only chooses `root` / whitelist from config.

---

## 9. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Import side effects in packages | Document “register() only”; load in isolated call; catch exceptions |
| Tool name collisions | Stable sort + last-wins + report/log |
| Packages depending on App domain | Contract AST test + code review |
| Scope creep into package-manager | Exit criteria fixed to local load + echo; no install CLI |
| Breaking agent isomorphism | Keep loader thin; no changes to loop semantics |

---

## 10. Definition of done (checklist)

- [ ] `capability_packages/` convention documented + `echo_example` present  
- [ ] `load_capability_packages` / `apply_capability_report` implemented  
- [ ] Failed package does not crash process (`strict=False`)  
- [ ] C1: Agent(faux) calls capability-provided tool  
- [ ] Contract tests: no remote install path; no `competitive_app` imports  
- [ ] P1+P2 offline suite still green  
- [ ] `P3_module_map.md` closed  
- [ ] Roadmap P3=`done`; this plan `completed`  

---

## 11. Suggested first coding session

1. G0 offline green.  
2. A1 scaffold loader package + `capability_packages/`.  
3. B1–B2 discover + single load with fixtures.  
4. B5 `echo_example`.  
5. B4 apply + C1 faux integration.  
6. C0 contract + C3 docs.

---

## 12. Revision log

| Version | Date | Note |
|---------|------|------|
| 0.1.0 | 2026-07-23 | Initial P3 plan: local-only loader under `pi_agent.capability_loader`, register(api) convention, echo_example exit smoke, no package-manager. Depends on P2 completed. |
