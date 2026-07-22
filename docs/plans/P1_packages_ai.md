# Plan: P1 — Full isomorphic port of `packages/ai`

| Field | Value |
|-------|--------|
| **plan_id** | `P1-packages-ai` |
| **plan_version** | `0.1.0` |
| **status** | **active** |
| **created** | 2026-07-22 |
| **roadmap** | [`docs/ROADMAP.md`](../ROADMAP.md) stage **P1** |
| **contract** | [`docs/contracts/ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.1** |
| **upstream** | https://github.com/earendil-works/pi **`main`** → `packages/ai/**` |
| **upstream_snapshot** | main `@ 75e6123aba58342d5e464c5b8417effa3dc441d2` (2026-07-22; re-fetch before coding) |
| **upstream_npm** | `@earendil-works/pi-ai` (observed `0.81.1` at snapshot) |
| **target** | `packages/ai/` → import `earendil_works.pi_ai` |
| **tests** | `tests/packages/ai/` |

---

## 0. Purpose of this plan

1. Give **serial, checkable steps** so implementation does not skip modules or invent a second architecture.
2. Define **contract / isomorphism drift tests** that fail if the port leaves the frozen baseline.
3. Separate **scaffold** from **port** from **exit review** so progress is honest.

**Non-goals of this plan:** P2 agent, P3 capability loader, P4 competitive features, coding-agent TUI, npm install marketplace.

---

## 1. Binding constraints (copy of contract for implementers)

| ID | Must |
|----|------|
| D1 | Single-process **Python 3.12+** |
| D4 / D15 | **Full** TS→Python isomorphic port of main `packages/ai` (not a thin wrapper) |
| D14 | Align to **current main**, not a frozen ancient tag as permanent truth |
| D17 / D18 | Path `packages/ai/`; import `earendil_works.pi_ai` |
| D20 | **asyncio** for public stream/complete APIs |
| D21 | **Pydantic v2** where validation is required (tool/schema surfaces as they appear in ai; TypeBox semantics → Pydantic) |
| D16 / G8 | Finish whole P1 before claiming agent/app work |
| G4 / G9 | Directory & behavior map to main; no parallel self-invented kernel tree |
| — | **No** LangChain / second LLM framework |
| — | Host-only deltas allowed: language/runtime (no Node/jiti/bun-specific bits as hard deps); document each intentional delta in §7 |

---

## 2. Upstream module map (must remain mappable)

Re-fetch main before Phase B. Snapshot layout (informational):

### 2.1 Top-level `packages/ai`

| Upstream | Python target (expected) | Notes |
|----------|--------------------------|--------|
| `src/index.ts` | `earendil_works/pi_ai/__init__.py` (+ public re-exports) | Core, side-effect free public surface |
| `src/types.ts` | `.../types.py` | Api, Model, Context, events, usage |
| `src/models.ts` / `models-store.ts` / `model-catalog.ts` | `models.py`, `models_store.py`, `model_catalog.py` | `Models` collection, registry |
| `src/models.generated.ts` | `models_generated.py` or generated data | Catalog data; regen strategy in §6 |
| `src/providers/**` | `providers/**` | One factory per provider + `all` + `faux` |
| `src/api/**` | `api/**` | Wire protocols: stream / streamSimple |
| `src/auth/**` | `auth/**` | credentials, oauth helpers |
| `src/utils/**` | `utils/**` | event-stream, retry, validation, uuid, … |
| `src/compat.ts` + `compat/**` | `compat/**` | Legacy global API; keep boundary |
| `src/images*.ts`, `image-models*` | `images*.py` | Image gen path |
| `src/session-resources.ts` | `session_resources.py` | |
| `src/env-api-keys.ts` | `env_api_keys.py` | |
| `src/oauth.ts`, `bun-oauth.ts`, `cli.ts` | host-adapted or optional modules | Bun-only / CLI: see §7 |
| `test/**` | behavioral ports under `tests/packages/ai/` | Not 1:1 filename required; **behavior** required |
| `scripts/*generate*` | optional Python or keep TS scripts offline | Document how catalogs update |

### 2.2 Public export surface (isomorphism checklist)

Upstream `index.ts` exports (must have Python equivalents or documented host-only omission):

- TypeBox re-export → **Pydantic / schema helpers** (documented mapping, not TypeBox runtime)
- API option types (Anthropic, OpenAI*, Google*, Bedrock, Mistral, PiMessages, …)
- `api/lazy` lazy loaders
- `auth/*` (context, credential-store, helpers, types)
- OAuth-related types from compat extension types
- `images-models`, `models`, `models-store`
- `providers/faux`
- `session-resources`, `types`
- utils: diagnostics, event-stream, json-parse, overflow, retry, text, validation, uuid, typebox-helpers→pydantic helpers

Subpath exports (package.json):

| Upstream export | Python import convention |
|-----------------|---------------------------|
| `@earendil-works/pi-ai` | `earendil_works.pi_ai` |
| `.../compat` | `earendil_works.pi_ai.compat` |
| `.../providers/*` | `earendil_works.pi_ai.providers.<name>` |
| `.../api/*` | `earendil_works.pi_ai.api.<name>` |
| `.../oauth` | `earendil_works.pi_ai.oauth` (if ported) |
| `.../bedrock-provider` | `earendil_works.pi_ai.bedrock_provider` |

### 2.3 Provider inventory (full port — no “core only”)

Each of these must exist as a mappable module (or explicit defer **only** if main removes it; not for convenience):

`amazon-bedrock`, `ant-ling`, `anthropic`, `azure-openai-responses`, `cerebras`, `cloudflare-ai-gateway`, `cloudflare-workers-ai`, `deepseek`, `faux`, `fireworks`, `github-copilot`, `google`, `google-vertex`, `groq`, `huggingface`, `kimi-coding`, `minimax`, `minimax-cn`, `mistral`, `moonshotai`, `moonshotai-cn`, `nvidia`, `openai`, `openai-codex`, `opencode`, `opencode-go`, `openrouter`, `qwen-token-plan`, `qwen-token-plan-cn`, `radius`, `together`, `vercel-ai-gateway`, `xai`, `xiaomi`, `xiaomi-token-plan-cn`, `xiaomi-token-plan-ams`, `xiaomi-token-plan-sgp`, `zai`, `zai-coding-cn`, plus `providers/all` and image register-builtins.

### 2.4 API implementation inventory

`anthropic-messages`, `azure-openai-responses`, `bedrock-converse-stream`, `google-generative-ai`, `google-vertex`, `mistral-conversations`, `openai-codex-responses`, `openai-completions`, `openai-responses`, `openrouter-images`, `pi-messages`, plus shared (`lazy`, `transform-messages`, `simple-options`, openai shared helpers, cloudflare, github-copilot-headers, …).

---

## 3. Target repo layout after P1 (scaffold + ai)

```text
pi4competitive/
  agents.md
  pyproject.toml                 # workspace root
  .gitignore                     # data/, .env, .venv, __pycache__, .codegraph/db noise if needed
  packages/
    ai/
      pyproject.toml             # name packaging for earendil_works.pi_ai
      README.md                  # upstream: packages/ai note
      src/earendil_works/pi_ai/
        __init__.py
        types.py
        models.py
        ...                      # mapped 1:1-ish to upstream src/
        api/
        auth/
        providers/
        utils/
        compat/
    agent/                       # placeholder only until P2
  capability_packages/           # empty + .gitkeep until P3
  competitive_app/               # placeholder only until P4
  config/settings.example.yaml
  data/sessions/.gitkeep         # data/ gitignored except keep pattern if desired
  tests/
    packages/ai/
      contract/                  # drift / layout / import / no-second-framework
      unit/
      integration/               # faux + recorded HTTP
      fixtures/
  docs/
    contracts/
    ROADMAP.md
    plans/P1_packages_ai.md      # this file
  vendor/                        # optional: shallow clone or sparse checkout of upstream for diff (gitignored or submodule — choose one in Phase A and stick)
```

---

## 4. Status board (update as you go)

Copy this table into PR descriptions. Status: `todo` | `in_progress` | `done` | `blocked`.

| Step | Phase | Status | Owner note |
|------|-------|--------|------------|
| A0 | Bootstrap git + codegraph | **done** (2026-07-22) | `git init`, branch `main`, `codegraph init` |
| A1 | Scaffold monorepo paths + pyproject + gitignore | todo | |
| A2 | Pin upstream fetch method + record SHA | todo | |
| A3 | Module map file `docs/plans/P1_module_map.md` generated from main | todo | |
| B0 | Core types + event stream + validation utils | todo | |
| B1 | Models collection + models-store + catalog read path | todo | |
| B2 | Faux provider + end-to-end stream/complete on faux | todo | |
| B3 | Auth context + credential store + env keys | todo | |
| B4 | API: openai-completions + openai-responses | todo | |
| B5 | API: anthropic-messages | todo | |
| B6 | API: google-generative-ai + google-vertex + shared | todo | |
| B7 | API: remaining (bedrock, mistral, codex, azure, pi-messages, images) | todo | |
| B8 | Providers: factories for all inventory §2.3 | todo | |
| B9 | `providers/all` + lazy loading semantics | todo | |
| B10 | Compat layer + legacy aliases | todo | |
| B11 | Images pipeline | todo | |
| B12 | OAuth / host-adapted auth flows | todo | |
| B13 | CLI (optional host tool) if required by parity | todo | |
| C0 | Contract-drift test suite green | todo | |
| C1 | Behavioral suite (unit + faux + selected recorded) green | todo | |
| C2 | Provider/API smoke matrix N samples vs main docs | todo | |
| C3 | Roadmap §5 → `P1=done` + plan status archived | todo | |

**Rule:** do not start B4+ until B0–B2 green. Do not mark P1 done until C0–C2 green.

---

## 5. Phased implementation steps

### Phase A — Scaffold & source pin (no LLM behavior yet)

**A1. Scaffold**

1. Create layout §3 (placeholders for agent/app/capability).
2. Root `pyproject.toml`: workspace, pytest, ruff optional, python ≥3.12.
3. `packages/ai/pyproject.toml`: package `earendil_works.pi_ai`, deps planned (httpx/anyio, pydantic, provider SDKs as needed).
4. `.gitignore`: `.env`, `data/` (except documented keepers), `.venv/`, `__pycache__/`, `*.pyc`, dist, coverage; keep `.codegraph/` policy as tool default (db may be local).
5. `config/settings.example.yaml` stub (keys empty; no secrets).
6. Empty tests package with `conftest.py`.
7. `codegraph index -f` after files exist.

**A2. Upstream pin method**

Choose one and document in this plan’s revision note:

- **Preferred:** sparse checkout / shallow clone of pi into `vendor/earendil-works-pi` (gitignored) or a documented `scripts/fetch_upstream_ai.sh`.
- Always record `UPSTREAM_SHA` in the PR (not a permanent lock file unless team later wants one).

**A3. Module map artifact**

Generate `docs/plans/P1_module_map.md`:

| upstream path | python path | status | notes |
|---------------|-------------|--------|-------|
| `src/types.ts` | `.../types.py` | todo | |

Update status column as modules land. **Drift rule:** a PR that adds Python modules with no map row fails review.

**Exit A:** layout exists; empty package imports; module map committed; codegraph non-empty for scaffold files.

---

### Phase B — Isomorphic port (serial modules)

#### B0 — Core types & stream primitives

Port:

- Message / ContentBlock / Tool / Context / Usage / Cost
- Stream event union (`start`, `text_*`, `thinking_*`, `toolcall_*`, `done`, `error`, …) matching upstream names
- `AssistantMessageEventStream` asyncio async-iterator + `result()`
- abort signal mapping (`asyncio.Event` / `AbortController` analogue)
- validation helpers; uuidv7; json partial parse strategy
- TypeBox → Pydantic mapping utilities for tool parameters

**Tests:** event ordering on a fake generator; serialization round-trip for Context; validation reject bad tool args.

#### B1 — Models collection

Port `createModels` / register provider / `getModel` / `getModels` / `stream` / `complete` / `streamSimple` / `completeSimple` routing.

**Tests:** register faux; lookup; unknown model errors; options passthrough types.

#### B2 — Faux provider (critical for offline CI)

Port `providers/faux` fully. All higher phases use it for default CI.

**Tests:** scripted text, tool calls, thinking, error, abort — mirror upstream `faux-provider.test.ts` intent.

#### B3 — Auth

Credential store, resolve order (explicit key → env → store), provider env overrides.

**Tests:** precedence table; no secret leakage in `repr`/logs helpers if any.

#### B4–B7 — API implementations

For each API module:

1. Port `stream` + `streamSimple` contracts.
2. Port message transforms and tool-call partial JSON behavior.
3. Map SDK clients to async Python equivalents (official SDKs or httpx).
4. Add **recorded** fixtures for request shape golden tests (redact secrets).
5. Mark module `done` in module map only when unit + at least one offline fixture test pass.

**Minimum CI without live keys:** transform + payload build + faux path.  
**Optional live e2e:** mark `@pytest.mark.live` and skip unless env keys present.

#### B8–B9 — Providers

Each factory: catalog + api binding + auth hooks. `providers/all.builtin_models()` registers full set.

**Tests:** every provider id in §2.3 is importable and registers ≥0 models (dynamic providers may be 0 until configured); `builtin_models()` does not import competitive_app.

#### B10 — Compat

Preserve legacy global API surface if main still ships it — agents/apps depending on compat must not break later.

#### B11–B13 — Images, OAuth, CLI

Port or document host-only substitute per §7. OAuth browser flows: Python stdlib/http server analogue; no Bun requirement.

**Exit B:** module map all rows `done` or `host-delta` with ADR/plan note; package importable as `earendil_works.pi_ai`.

---

### Phase C — Hardening & exit gate

1. Run full `tests/packages/ai` including **contract/** suite (§6).
2. Sample N providers against upstream README behavior (manual or recorded).
3. `codegraph explore "Models stream"` smoke — graph sees symbols.
4. Update `docs/ROADMAP.md` §5 P1 → `done`.
5. Set this plan `status: completed` and bump `plan_version` if needed.

**P1 exit criteria (roadmap — all required):**

| # | Criterion | Evidence |
|---|-----------|----------|
| 1 | Directory/module responsibilities mappable to upstream | `P1_module_map.md` 100% rows closed |
| 2 | Public stream/model/usage alignable with main | contract + behavioral tests |
| 3 | `tests/packages/ai/` repeatable | CI offline green |
| 4 | No second LLM framework | contract test `test_no_forbidden_deps` |

---

## 6. Test strategy (prevent contract & isomorphism drift)

### 6.1 Layers

| Layer | Path | Purpose | CI |
|-------|------|---------|-----|
| **Contract / drift** | `tests/packages/ai/contract/` | Frozen architecture + layout + imports + bans | **required always** |
| **Unit** | `tests/packages/ai/unit/` | Pure transforms, validation, cost math, catalogs | **required** |
| **Faux integration** | `tests/packages/ai/integration/faux/` | Full stream/complete without network | **required** |
| **Recorded HTTP** | `tests/packages/ai/integration/recorded/` | Golden request/response shapes | **required** when fixtures exist |
| **Live** | `tests/packages/ai/integration/live/` | Real provider smoke | optional, env-gated |
| **Upstream parity (optional tooling)** | scripts comparing export lists | Detect missing public symbols | recommended in CI |

### 6.2 Contract / anti-drift tests (must implement in C0; scaffold stubs in A1)

Implement as pytest modules. Each test maps to a contract/roadmap rule.

#### C-LAYOUT — repository shape

| Test id | Asserts | Fails when |
|---------|---------|------------|
| `test_packages_ai_path_exists` | `packages/ai/src/earendil_works/pi_ai` exists | path renamed to `pi_core` etc. (D17) |
| `test_import_name_earendil_works_pi_ai` | `import earendil_works.pi_ai` succeeds | wrong package name (D18) |
| `test_no_top_level_pi_core_package` | forbidden paths absent | parallel kernel tree (G9) |
| `test_capability_packages_not_inside_ai` | no business capability packages under `packages/ai` | scope bleed |
| `test_data_sessions_not_required_for_ai_import` | importing ai does not create/require session store | P2 leak into P1 |

#### C-DEPS — stack & bans

| Test id | Asserts | Fails when |
|---------|---------|------------|
| `test_no_forbidden_llm_frameworks` | `importlib` / package metadata: no langchain, llama_index, haystack, semantic_kernel as deps of `pi_ai` | second framework (D15) |
| `test_no_nodejs_runtime_required` | package does not shell out to `node`/`npx` on import or faux stream | dual-process regression (D1) |
| `test_pydantic_v2_available_for_validation` | pydantic major ≥2 when validation helpers used | wrong stack (D21) |
| `test_public_stream_apis_are_async` | `inspect.iscoroutinefunction` / async iterator protocols on `Models.stream` / `complete` | sync-only kernel (D20) |

#### C-PUBLIC-API — export parity

| Test id | Asserts | Fails when |
|---------|---------|------------|
| `test_public_symbols_minimum_set` | required names exist on `earendil_works.pi_ai` (Context, Tool, Model fields, stream events, faux, create_models/builtin_models, usage fields) | silent API shrink |
| `test_provider_modules_exist` | for each id in §2.3 inventory, module import path resolves | “core only” incomplete port |
| `test_api_modules_exist` | for each id in §2.4 inventory, module resolves | missing wire protocol |
| `test_subpath_imports` | `providers.faux`, `providers.all`, sample `api.*` importable | broken packaging |

Maintain `tests/packages/ai/contract/expected_providers.txt` and `expected_apis.txt` generated from module map; **updating the list requires plan note**, not silent delete.

#### C-BEHAVIOR-CORE — stream / model / usage

| Test id | Asserts | Fails when |
|---------|---------|------------|
| `test_faux_stream_event_order` | start → text_start → text_delta* → text_end → done | event protocol drift |
| `test_faux_toolcall_partial_then_end` | toolcall_start/delta/end + arguments object | tool streaming broken |
| `test_complete_equals_stream_result` | `complete` message equals draining stream `result()` for same faux script | dual codepaths diverge |
| `test_usage_fields_present` | input/output/cache/cost.total numeric shape | usage model drift |
| `test_context_messages_roundtrip_json` | Context serialize/deserialize stable | handoff/session prep broken |
| `test_abort_stops_stream` | cancel mid-stream yields error/abort terminal | abort regression |
| `test_models_get_model_routing` | correct provider serves model id | registry routing bugs |

#### C-TRANSFORM — message / tool parity (per major API)

| Test id | Asserts |
|---------|---------|
| `test_openai_completions_payload_tools_shape` | tools JSON schema shape from Tool definitions |
| `test_anthropic_messages_tool_name_normalization` | parity with upstream tests intent |
| `test_google_tools_convert` | shared convert tools |
| `test_cross_provider_handoff_context` | same Context accepted by faux after “handoff” |

Use **golden JSON files** under `tests/packages/ai/fixtures/payloads/` redacted.

#### C-AUTH

| Test id | Asserts |
|---------|---------|
| `test_api_key_precedence` | options.apiKey > provider env > process env (document exact order from upstream) |
| `test_missing_key_error_is_structured` | not raw traceback-only |

#### C-SECURITY-HYGIENE

| Test id | Asserts |
|---------|---------|
| `test_no_secrets_in_repo_patterns` | scan tree for high-entropy key assignments in non-example files (light) |
| `test_settings_example_has_no_live_secrets` | example yaml placeholders only |

#### C-PROCESS / SERIAL ROADMAP (repo-level)

| Test id | Asserts | Fails when |
|---------|---------|------------|
| `test_competitive_app_has_no_runtime_dep_on_incomplete_agent` | until roadmap says P2 done, `competitive_app` must not import missing agent as required prod path — **or** app remains placeholder empty | skip-ahead (D16) |
| `test_ai_package_does_not_import_competitive_app` | dependency direction | inverted deps |
| `test_ai_package_does_not_import_capability_packages` | ai stays generic | domain leak |

### 6.3 Mapping upstream tests → pytest

Do **not** require identical filenames. Require **intent coverage**:

| Upstream test themes (examples) | Python home |
|---------------------------------|-------------|
| `faux-provider.test.ts` | `integration/faux/` |
| `stream.test.ts`, `tokens.test.ts`, `total-tokens.test.ts` | `unit/` + faux |
| `validation.test.ts`, `uuid.test.ts`, `text.test.ts` | `unit/` |
| `*sse-parsing*`, `*payload*`, `*convert*` | `unit/` + fixtures |
| `*oauth*` | unit with mocked HTTP; live optional |
| `*e2e*` | `integration/live` or recorded |

When porting a module, open the matching upstream test and tick a line in the module map: `tests: yes/partial/no`.

### 6.4 Faux / recorded policy (repeatability)

1. **Default CI:** no network, no API keys.
2. Faux scripts cover: plain text, multi-block, tool call, multi tool, thinking, empty, error mid-stream, abort.
3. Recorded fixtures: store method, URL host path template, headers **names** (not secret values), body JSON. Replay with `respx`/`httpx.MockTransport` or equivalent.
4. Live tests: `@pytest.mark.live` + `pytest -m "not live"` default.

### 6.5 Suggested pytest layout & commands

```bash
# offline CI (P1 gate)
pytest tests/packages/ai -m "not live" -q

# contract only (fast PR check)
pytest tests/packages/ai/contract -q

# optional live
pytest tests/packages/ai -m live --maxfail=1
```

`pyproject.toml` markers: `live`, `slow`.

### 6.6 Manual review checklist (exit C2)

- [ ] N≥5 providers: factory import + model list non-crash
- [ ] N≥3 APIs: payload golden matches intentional upstream shape
- [ ] README quickstart translated snippet runs on faux
- [ ] Module map has zero `todo` rows
- [ ] No LangChain import anywhere under `packages/ai`
- [ ] `codegraph status` shows expected file count; `codegraph explore "stream"` finds Python symbols
- [ ] Roadmap drift checklist §6 all checked for the PR

---

## 7. Intentional host-only deltas (allow-list)

Only these classes of divergence are allowed without ADR. **Anything else needs ADR + contract bump.**

| Delta | Reason | Required mitigation |
|-------|--------|----------------------|
| TypeBox → Pydantic v2 | TS schema runtime ≠ Python | Document mapping; validation tests |
| Node streams → asyncio AsyncIterator | runtime | event name parity tests |
| Bun OAuth / bun-oauth | no Bun runtime | Python oauth module; tests with mocks |
| jiti dynamic TS load | N/A | Python imports / importlib |
| Generated model catalogs | may vendor JSON instead of TS codegen | `check:model-data` equivalent test |
| CLI binary name | packaging | optional `pi-ai` console_script |
| SDK version pins | Python packages differ | behavioral tests over version chasing |

**Not allowed as “host delta”:** dropping most providers; replacing stream event protocol; introducing App domain types into ai; requiring Node side-car.

---

## 8. Progress hygiene (avoid implementation drift)

1. **One phase row at a time** on §4 status board; set `in_progress` before coding.
2. **Module map first** when adding files; no orphan modules.
3. **Tests with code** for B0–B2; for B4+ at least one offline test per API module before next.
4. **No P2/P3/P4 code** in P1 PRs except empty placeholders from A1.
5. **Re-fetch main** at start of each major provider wave; if upstream reorganized, update module map + this plan revision before coding.
6. **CodeGraph:** `codegraph sync` after large moves; use `callers` before renames.
7. PR title prefix: `P1:` and list board step ids (e.g. `P1: B2 faux provider`).

---

## 9. Definition of Done (P1)

All must be true:

1. §4 board A1–C2 = `done`.
2. Roadmap exit criteria ①–④ satisfied with evidence paths linked in final PR.
3. Contract tests §6.2 all green in offline CI.
4. `earendil_works.pi_ai` is the only LLM kernel package in-tree.
5. This plan status set to `completed`; roadmap P1 = `done`.
6. **No** claim that agent/app is ready.

---

## 10. Immediate next actions (after this plan lands)

1. Execute **A1** scaffold (pyproject, dirs, gitignore, empty package).
2. Execute **A2–A3** fetch upstream + write `P1_module_map.md`.
3. Start **B0** types + event stream with unit tests.
4. Keep CodeGraph fresh: `codegraph index -f` after scaffold.

Do **not** open P4 feature design in parallel unless an explicit second track is requested.

---

## 11. Revision log

| Version | Date | Note |
|---------|------|------|
| 0.1.0 | 2026-07-22 | Initial plan: phases A–C, full module inventory, contract test matrix, status board. Upstream SHA `75e6123a…`. |
