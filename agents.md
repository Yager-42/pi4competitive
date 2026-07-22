# Agent Guide — CompetitorLens (`pi4competitive`)

This file is for humans and coding agents working in this repo.

## Source of truth (do not drift)

| Doc | Role |
|-----|------|
| [`docs/contracts/ARCHITECTURE_CONTRACT.md`](docs/contracts/ARCHITECTURE_CONTRACT.md) | **v0.3.1 frozen baseline** — process, paths, imports, stack, load rules |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Serial phases P1→P4 and exit gates |
| [`docs/plans/P1_packages_ai.md`](docs/plans/P1_packages_ai.md) | P1 plan (**completed**) — `packages/ai` / `earendil_works.pi_ai` |
| [`docs/plans/P2_packages_agent.md`](docs/plans/P2_packages_agent.md) | **Active implementation plan** for P2 (`packages/agent`) |
| `docs/contracts/adr/*` | Architecture Decision Records |

**Rules:**

1. Architecture changes require **ADR + contract version bump**. Chat-only architecture changes are invalid.
2. Implementation order is **serial**: P1 `packages/ai` → P2 `packages/agent` → P3 local loader → P4 `competitive_app`.
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

- Active phase checklist: `docs/plans/P2_packages_agent.md` status board (P1 completed).
- Roadmap phase flags: `docs/ROADMAP.md` §5.
- Do not mark `P2=done` until JSONL resume exit smoke and the plan’s contract tests pass.

### PR checklist (every PR)

Reuse roadmap §6 plus:

- [ ] Stage allowed for this change?
- [ ] Module map still matches upstream `packages/ai` (or documented intentional host-only delta)?
- [ ] Contract-drift tests still green?
- [ ] CodeGraph re-synced if layout changed?
- [ ] No business types leaked into `packages/ai`?

---

## Quick start for a new agent session

1. Read this file + contract v0.3.1 + active plan status board.
2. `codegraph status` — if empty/stale and source exists, `codegraph sync` or `index -f`.
3. `codegraph explore` / `node` for the area you will change.
4. Implement only the current plan phase; update checklist boxes when done.
5. Run the plan’s required tests for that phase before claiming completion.
