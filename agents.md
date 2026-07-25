# Agent Guide — CompetitorLens (`pi4competitive`)

This file is for humans and coding agents working in this repo.

## Source of truth (do not drift)

| Doc | Role |
|-----|------|
| [`docs/contracts/ARCHITECTURE_CONTRACT.md`](docs/contracts/ARCHITECTURE_CONTRACT.md) | **v0.3.4** — process, paths, imports, stack; P3 local subset (ADR 0006); **P3.1 engine extensions (ADR 0008)**; P4 旧仓 pin (ADR 0007) |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Serial phases P1→P3→**P3.1**→P4 and exit gates |
| [`docs/features/`](docs/features/) | Per-feature boundary contracts; see README index |
| [`docs/features/search_capability_packages_v1.md`](docs/features/search_capability_packages_v1.md) | search capability v1 **frozen v0.1.12**（F-S1…F-S18 + §10） |
| [`docs/features/agent_engine_extensions_v1.md`](docs/features/agent_engine_extensions_v1.md) | agent engine extensions **frozen v0.2.2**（P3.1；Offline + Live L3a/L3b） |
| [`docs/features/competitive_app_http_v1.md`](docs/features/competitive_app_http_v1.md) | P4 app HTTP 边界 **frozen v0.1.3**（`competitive-app-http-v1`；14 路由骨架；研究 workflow 占位） |
| [`docs/plans/P1_packages_ai.md`](docs/plans/P1_packages_ai.md) | P1 plan (**completed**) — `packages/ai` |
| [`docs/plans/P2_packages_agent.md`](docs/plans/P2_packages_agent.md) | P2 plan (**completed**) — `packages/agent` |
| [`docs/plans/P3_capability_loader.md`](docs/plans/P3_capability_loader.md) | P3 plan (**completed**) — package-manager local subset |
| [`docs/plans/P3_1_agent_engine_extensions.md`](docs/plans/P3_1_agent_engine_extensions.md) | P3.1 engine extension runtime (**completed v0.2.3**); map [`P3_1_module_map.md`](docs/plans/P3_1_module_map.md) |
| [`docs/plans/P4_search_capability_packages.md`](docs/plans/P4_search_capability_packages.md) | search capability packages v1 (**completed** implementation; feature frozen) |
| [`docs/plans/P4_competitive_app_http.md`](docs/plans/P4_competitive_app_http.md) | **P4 active** — competitive_app HTTP 骨架（v0.2.0；14 路由；研究 workflow 占位） |
| [`docs/contracts/adr/0006-package-manager-local-isomorphic-subset.md`](docs/contracts/adr/0006-package-manager-local-isomorphic-subset.md) | ADR: port subset, omit install/npm/git/home |
| [`docs/contracts/adr/0007-legacy-repo-capability-reference.md`](docs/contracts/adr/0007-legacy-repo-capability-reference.md) | ADR: 旧仓 = `competitive-agent`（能力参考 only） |
| [`docs/contracts/adr/0008-agent-engine-extensions-runtime.md`](docs/contracts/adr/0008-agent-engine-extensions-runtime.md) | ADR: P3.1 extension runtime S-engine |
| `docs/contracts/adr/*` | Architecture Decision Records |

**Rules:**

1. Architecture changes require **ADR + contract version bump**. Chat-only architecture changes are invalid.
2. Implementation order is **serial**: P1 `packages/ai` → P2 `packages/agent` → P3 local loader → **P3.1 engine extensions** → P4 `competitive_app`.
3. Pi base = **TS→Python isomorphic port** of upstream `earendil-works/pi` **`main`**, not an inspired rewrite.
4. Import map: `packages/ai` → `earendil_works.pi_ai`; `packages/agent` → `earendil_works.pi_agent`.
5. Do **not** implement P4 business features until P1–P3 exit gates pass and features are frozen separately.

---

## CodeGraph (required navigation tool)

This repo is indexed by **CodeGraph** (`.codegraph/` at repo root). Prefer CodeGraph **before** broad `grep`/`find`/full-file reads when locating or understanding code.

### Setup (once per clone)

```bash
# from repo root
codegraph init          # creates .codegraph/ and builds the index
codegraph status        # verify files/nodes/edges
```

If the workspace was empty when first initialized (docs-only), re-index after code lands:

```bash
codegraph index -f      # full re-index
# or, after incremental edits:
codegraph sync
```

### When to use CodeGraph

| Need | Command | Prefer over |
|------|---------|-------------|
| “Where is X implemented and who calls it?” | `codegraph explore "<question or symbols>"` | multi-file grep + manual reads |
| One symbol’s source + callers/callees | `codegraph node <SymbolName>` | hoping open files |
| Read a file with line numbers + dependents | `codegraph node path/to/file.py` | raw open without graph context |
| Symbol name search | `codegraph query <search>` | ad-hoc text search for definitions |
| Callers / callees only | `codegraph callers <sym>` / `codegraph callees <sym>` | hand-rolled reference search |
| Change impact | `codegraph impact <sym>` | guessing blast radius |
| Which tests touch changed files | `codegraph affected <files...>` | running the whole suite blindly |
| Indexed tree | `codegraph files` | `find` / recursive `ls` |

### Shell examples

```bash
# Explore an area (symbols + call paths in one shot)
codegraph explore "Models.stream streamSimple"
codegraph explore "how does auth credential resolution work"

# Single symbol
codegraph node createModels
codegraph node stream --file packages/ai/src/earendil_works/pi_ai/models.py

# File mode (line-numbered + dependents)
codegraph node packages/ai/src/earendil_works/pi_ai/types.py --offset 1 --limit 80

# Search / graph queries
codegraph query stream -k function -l 20
codegraph callers get_model
codegraph callees builtinModels
codegraph impact Context
codegraph affected packages/ai/src/earendil_works/pi_ai/api/openai_responses.py

# Structure from index
codegraph files --filter packages/ai --max-depth 4
codegraph status
```

### Agent rules for CodeGraph

1. **Before** large exploratory greps across `packages/**`, run `codegraph explore` or `codegraph query`.
2. **Before** renaming or changing an exported symbol, run `codegraph callers <symbol>` (or `impact`) and update every callsite.
3. After adding/moving many files in a session, run `codegraph sync` (or `codegraph index -f` if the index looks stale).
4. If `codegraph status` shows **0 files** while source exists, re-index; do not assume “no code”.
5. MCP (when available): tools mirror CLI — `codegraph_explore` ≈ `explore`, `codegraph_node` ≈ `node`. Prefer those when listed in the session.
6. CodeGraph is **not** a substitute for reading the architecture contract or the active plan; use it for **code** navigation.

### Not CodeGraph’s job

- Architecture decisions (use contract + ADR).
- Upstream TS source of truth (use `https://github.com/earendil-works/pi` `main`).
- Running tests (use `pytest` / project scripts).
- Editing files (use normal edit tools).

---

## Upstream (port source)

| Item | Value |
|------|--------|
| Repo | https://github.com/earendil-works/pi |
| Branch | **`main` only** |
| P1 tree | `packages/ai/**` |
| Package (npm) | `@earendil-works/pi-ai` |
| Port target | `packages/ai` → `earendil_works.pi_ai` |

Record the main SHA used for a port PR in the PR body (forensics only; no mandatory lock file).

---

## Working conventions

- Python **3.12+**, **asyncio** for public ai/agent APIs, **Pydantic v2** for validation where needed.
- No second LLM framework (no LangChain/etc.).
- Secrets never in git (`.env` gitignored); `config/settings.example.yaml` only.
- Session JSONL SoT: `data/sessions/` (`data/` gitignored) — **P2**, not P1.
- Capability packages: local `capability_packages/` only — **P3**, not P1.

### Progress tracking

- Completed phase checklist: `docs/plans/P3_1_agent_engine_extensions.md` status board.
- Roadmap phase flags: `docs/ROADMAP.md` §5.
- Next work must follow the next frozen P4 feature/plan; do not infer an unfrozen workflow.

### PR checklist (every PR)

Reuse roadmap §6 plus:

- [ ] Stage allowed for this change?
- [ ] Module map still matches upstream `packages/ai` (or documented intentional host-only delta)?
- [ ] Contract-drift tests still green?
- [ ] CodeGraph re-synced if layout changed?
- [ ] No business types leaked into `packages/ai`?

---

## Quick start for a new agent session

1. Read this file + architecture contract v0.3.4 + the active frozen feature/plan.
2. `codegraph status` — if empty/stale and source exists, `codegraph sync` or `index -f`.
3. `codegraph explore` / `node` for the area you will change.
4. Implement only the current plan phase; update checklist boxes when done.
5. Run the plan’s required tests for that phase before claiming completion.
