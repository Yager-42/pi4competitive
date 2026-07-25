# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**CompetitorLens** (`pi4competitive`) — a Python isomorphic port of the TypeScript repo
[`earendil-works/pi`](https://github.com/earendil-works/pi) (`main` branch) plus a
competitive-intelligence FastAPI app built on top of it. Single process, asyncio, Pydantic v2.
The port is **isomorphic** (module boundaries + behavior map to upstream `main`), not an
inspired rewrite. A second legacy repo, [`xj120/competitive-agent`](https://github.com/xj120/competitive-agent)
(checked out alongside as `competitive-agent/`), is **capability reference only, never the Pi parent** (D12 / ADR 0007).

## Current status (as of contract v0.3.4 / roadmap v0.1.15)

- **P1** `packages/ai` — **done**
- **P2** `packages/agent` (core + harness) — **done**
- **P3** local capability loader (`package_manager/`) — **done** (ADR 0006: isomorphic *local subset* of coding-agent package-manager; install omitted)
- **P3.1** agent engine extension runtime (`extensions/`) — **done** (ADR 0008)
- **P4** `competitive_app` — **in progress**: DDD + FastAPI skeleton + 14 HTTP routes landed (feature `competitive-app-http-v1` v0.1.3 frozen; research workflow still placeholder). See [`docs/features/competitive_app_http_v1.md`](docs/features/competitive_app_http_v1.md).
- **Business capability v1 (search)** — **partial**: three search capability packages + five AgentTools implemented and feature-frozen; the `competitive_app` workflow that uses them is not yet wired.

P1–P3.1 are complete; P4 app skeleton is in. The research workflow (stage DAG, full report schema) is still unfrozen — the P4 task routes are placeholder until that feature is grilled and frozen.

## Source of truth (read these first; do not drift)

| Doc | Role |
|-----|------|
| [`agents.md`](agents.md) | Agent guide — working conventions, CodeGraph usage, PR checklist |
| [`docs/contracts/ARCHITECTURE_CONTRACT.md`](docs/contracts/ARCHITECTURE_CONTRACT.md) | **v0.3.4 frozen baseline** — binding decisions, quality gates |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Serial phases P1→P3→P3.1→P4, status board, exit gates |
| [`docs/features/`](docs/features/) | Per-feature boundary contracts (frozen). `search_capability_packages_v1.md` (v0.1.12), `agent_engine_extensions_v1.md` (v0.2.2) |
| [`docs/plans/`](docs/plans/) | Per-phase implementation plans + module maps (P1–P4, P3.1) |
| `docs/contracts/adr/*` | ADRs 0001–0008 |

**Architecture changes require an ADR + contract version bump. Chat-only architecture changes are invalid.** Each phase plan has a status board — update its checkboxes as you complete steps; a PR that adds files with no map row fails review.

## Commands

`uv` workspace (members: `packages/ai`, `packages/agent`, both editable-installed). pytest uses `--import-mode=importlib`, `asyncio_mode = "auto"`, markers `live` (real provider calls) and `slow`.

```bash
uv sync                                              # install workspace + dev deps
uv run pytest -m "not live" -q                       # full offline suite (default CI)
uv run pytest tests/packages/ai -m "not live" -q     # P1 suite
uv run pytest tests/packages/agent -m "not live" -q  # P2/P3/P3.1 suite
uv run pytest tests/packages/agent/contract -q      # contract/drift guards only (fast)
uv run pytest tests/packages/agent/integration/faux/test_agent_loop_tools.py::test_name -q  # single test
uv run pytest -m live --maxfail=1                    # real API calls (needs .env gateway)
ruff check . && ruff format .                        # lint + format (line-length 100, py312)
python scripts/smoke_live_model.py                   # live stream smoke, reads repo-root .env
bash scripts/fetch_upstream.sh                       # sparse-checkout upstream packages → vendor/
```

`data/` (incl. `data/sessions/` JSONL) and `.env` are gitignored. Live tests are env-gated and **not** exit-blocking — faux + JSONL smoke is the gate.

## Architecture

**Serial phases (cannot skip or reorder):**

```text
P1  packages/ai          full isomorphic port of upstream packages/ai            → done
P2  packages/agent       C-tier port of upstream packages/agent (core+harness)   → done
P3  package_manager/     isomorphic LOCAL subset of coding-agent package-manager → done
P3.1 extensions/         coding-agent core/extensions runtime (S-engine subset)  → done
P4  competitive_app      FastAPI + DDD + workflow (business features)            → todo
```

**Dependency direction (enforced by contract tests):**

```text
competitive_app → packages/agent → packages/ai
capability_packages/  →  loaded INTO agent via package_manager (never reverse-imported)
packages/agent | packages/ai  ↛  competitive_app.domain   (never import the app/domain)
```

**Import map:** `packages/ai` → `earendil_works.pi_ai`; `packages/agent` → `earendil_works.pi_agent` (incl. `.extensions`, `.package_manager`, `.harness`); `competitive_app` → `competitive_app`.

**P4 layering (not yet built):** DDD/hexagonal — `adapter/in/fastapi` → `application/workflow` (Process Manager) → `domain` (pure, no IO) → `adapter/out/persistence`. FastAPI routes must not stage orchestration; domain must not do IO.

**Sources of truth on disk:** agent conversation/tool/session tree = **JSONL** at `data/sessions/` (D24/D25 — not ephemeral `/tmp`; resume must not rely on memory). App **SQLite** is only a task/progress projection, never the conversation history.

### The ported packages

**`packages/ai`** (`earendil_works.pi_ai`, v0.81.1): `create_models`/`ModelsImpl` (`models.py`), `Model`/`Context`/`Tool`/`Usage`/`AssistantMessage` (`types.py`), ~37 provider factories in `providers/` (each with a `*_models.py` catalog from npm `@earendil-works/pi-ai@0.81.1`), wire-protocol builders + lazy loaders in `api/`, credential resolution/oauth in `auth/`. `faux_provider`/`faux_text`/`faux_tool_call` are offline test doubles.

**`packages/agent`** (`earendil_works.pi_agent`, v0.81.1) re-exports from `__init__.py`:
- **Core loop:** `Agent`, `agent_loop`/`agent_loop_continue`/`run_agent_loop*`, `AgentTool`/`AgentToolResult`/`AgentEvent`/`StreamFn`/`AbortController`, `set_default_stream_fn`.
- **Harness:** `AgentHarness`, `Session`, `JsonlSessionRepo`/`InMemorySessionRepo` + storages, `build_session_context`, compaction (`should_compact`/`compact`/`prepare_compaction`/`find_cut_point`), skills/system-prompt, built-in coding tools (`create_read_tool`/`create_write_tool`/`create_coding_tools`, edit/bash/image). `DEFAULT_SESSIONS_DIR_NAME` pins the `data/sessions` default.
- **P3 package_manager:** `load_capability_packages`(/`_sync`), `apply_capability_report`, `LocalPackageManager`, `LoadReport` — discover/parse/load `capability_packages/*`.
- **P3.1 extensions:** `create_extension_runtime`, `load_extensions`, `ExtensionRunner`, `ExtensionAPI`, `attach_extension_runtime`, `wrap_registered_tool(s)` — the engine extension runtime wired into the loop.

### Capability packages (`capability_packages/`)

Local-only, one subdir per package. A package declares resources via an optional `package.json` `pi` manifest (`extensions`/`skills`/`prompts` arrays, globs + `!exclusions`) **or** convention dirs (`extensions/` `*.py`, `skills/` `SKILL.md`, `prompts/` `*.md`). Extensions register tools:

```python
from earendil_works.pi_agent.types import AgentTool

async def _execute(tool_call_id, params, signal=None, on_update=None):
    return {"content": [{"type": "text", "text": "..."}], "details": {...}}

def register(api):
    api.registerTool(AgentTool(name="...", description="...", parameters={...}, execute=_execute))
```

Load + apply: `report = await load_capability_packages(); apply_capability_report(agent, report)` (filters: `enabled=[...]`/`disabled=[...]`/`strict=True`). Four packages exist: `echo_example`, `search_tavily`, `search_anysearch`, `search_grok`. **Capability packages run with full process privileges** — review before enabling; no remote download path exists.

## Critical constraints (easy to violate — enforced by contract tests)

1. **Isomorphic port, not rewrite.** Module boundaries and behavior must map to upstream `earendil-works/pi` `main`. Re-fetch upstream before porting; record the SHA in `docs/plans/UPSTREAM_SHA.txt`.
2. **One agent kernel only** = `packages/agent` (G3). No second agent package; the loader and extensions live *inside* `pi_agent`.
3. **No second LLM framework.** `langchain`, `langgraph`, `llama_index`, `haystack`, `semantic_kernel`, etc. are forbidden under `pi_ai`/`pi_agent` — an AST scan in `tests/packages/*/contract/test_deps.py` fails the build.
4. **No business/domain types in `packages/ai|agent`.** Capability packages and research workflow belong in `competitive_app` + `capability_packages/`, never in the ported base.
5. **Import direction:** `pi_agent → pi_ai` only. Agent/ai must not import `competitive_app` or `capability_packages`.
6. **Public ai/agent APIs are async** (asyncio, D20). Tool args validate via Pydantic v2 / JSON Schema (D21).
7. **Capability packages are local-only** (D5/D22 + ADR 0006): the loader is an isomorphic *local subset* of coding-agent package-manager (resolve/load/manifest/filter). **Omitted forever:** `install`, npm/git sources, `~/.pi` home discovery, `pi install` CLI, extension gallery. These must not appear as a default code path (throw / `NotImplementedError`, scanned by contract tests).
8. **Extension runtime (ADR 0008):** the loop emits **only** extension events (H1 — no parallel host hooks like `on_payload`/`transform_context` as a second path). Tools register via `registerTool` (M2 — no long-term `add_tool` compat layer). OUT items (TUI/`ui.*`/theme/session-tree events/install/home) must **not** appear in the public API; IN methods that are unwired must **throw, not silently no-op**.
9. **JSONL is the session SoT** at `data/sessions/` (D24/D25, G7). Don't default to OS temp as the sole store.
10. **Legacy repo is reference only.** `competitive-agent/` is for P4 business/workflow/domain shape ideas — never a Pi parent, never a 1:1 copy backlog (D12 / ADR 0007).
11. **Secrets never in git.** `.env` only; `config/settings.example.yaml` carries no live keys (scanned by `test_settings_hygiene.py`).
12. **PR title prefix** with the stage, e.g. `P4: search capability wiring`. Update the plan's status board rows as you complete them.

## Code navigation: CodeGraph

The repo is indexed by **CodeGraph** (`.codegraph/`). Prefer it before broad `grep`/`find` across `packages/**`:

```bash
codegraph status                              # 0 files while source exists → re-index, don't assume "no code"
codegraph explore "Agent agent_loop Session"  # symbols + call paths in one shot
codegraph node <SymbolName>                   # source + callers/callees
codegraph node path/to/file.py                # line-numbered file + dependents
codegraph callers <sym> / codegraph impact <sym>   # before renaming an exported symbol
codegraph affected <files...>                 # which tests touch changed files
codegraph sync                                # after incremental edits; index -f if stale
```

If MCP `codegraph_*` tools are listed in the session, prefer those over the CLI. CodeGraph is for **code** navigation only — it does not replace the contract, the active plan, or upstream `main` as source of truth.
