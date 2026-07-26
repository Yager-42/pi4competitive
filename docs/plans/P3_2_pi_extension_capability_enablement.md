# Plan: P3.2 — Pi extension capability enablement (Reasonix prefix cache)

| Field | Value |
|-------|--------|
| **plan_id** | `P3.2-pi-extension-capability-enablement` |
| **plan_version** | `0.1.1` |
| **status** | **in_progress** |
| **created** | 2026-07-26 |
| **updated** | 2026-07-26 |
| **roadmap** | [`docs/ROADMAP.md`](../ROADMAP.md) stage **P3.2** |
| **contract** | [`docs/contracts/ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.5** |
| **feature** | [`docs/features/reasonix_prefix_cache_v1.md`](../features/reasonix_prefix_cache_v1.md) **v0.1.0 frozen** — `reasonix-prefix-cache-v1` |
| **runtime baseline** | [`docs/features/agent_engine_extensions_v1.md`](../features/agent_engine_extensions_v1.md) **v0.3.0 frozen**（P3.1 baseline + P3.2 delta） |
| **ADR** | [0006 local package subset](../contracts/adr/0006-package-manager-local-isomorphic-subset.md) · [0008 extension runtime](../contracts/adr/0008-agent-engine-extensions-runtime.md) · **[0009 P3.2 enablement](../contracts/adr/0009-p3-2-pi-extension-capability-enablement.md)** |
| **depends_on** | **P3.1 done** — [`P3_1_agent_engine_extensions.md`](P3_1_agent_engine_extensions.md) **v0.2.4 completed baseline**; feature frozen; ADR 0009 accepted; contract **v0.3.5** |
| **upstream** | `earendil-works/pi` **`main`** → `packages/ai` cache transport/usage + coding-agent compaction / extension compact path |
| **upstream_snapshot** | same pin as ai/agent — see [`UPSTREAM_SHA.txt`](UPSTREAM_SHA.txt) |
| **target** | `packages/ai` cache parity · `packages/agent` generic `CompactionPlan` bridge · `capability_packages/reasonix_prefix_cache` |
| **tests** | Offline adapter / extension E2E / compaction / resume；Live opt-in **full-stack** warm-cache（loader → Reasonix extension → Harness → ai adapter → real provider → usage/E1）；Reasonix+search co-load |
| **non_goal** | Reasonix policy in core；ordered `enabled` load plan；TUI / install / npm / git / `~/.pi`；P4 App workflow；C/D/F pillars |

---

## 0. Purpose

1. **Enable** frozen `reasonix-prefix-cache-v1` (**A + B + E**) on the completed P3.1 S-engine baseline without inventing parallel hooks (ADR 0009).
2. **Port** missing upstream `packages/ai` cache request / usage / callback parity for **V1** adapter families (OpenAI-compatible + Anthropic Messages).
3. **Add** one minimal, provider-neutral host bridge: validated `CompactionPlan` transaction + harness `prepareNextTurn` checkpoint + real `ctx.compact()` / `getContextUsage()` bindings.
4. **Ship** local consumer package `capability_packages/reasonix_prefix_cache` that owns Reasonix policy only (canonicalize, epoch, plan, metrics observation).
5. **Prove** offline gates + one opt-in full-stack live warm hit through the official local-package/Harness path; prove Reasonix + search packages co-load without tool/lifecycle collision.

**Approach:** three-layer enablement (ai parity → agent bridge → local package). Not a full Reasonix host port; not a second agent kernel; not P4 App work.

**Non-goals of this plan:**

| Out of scope | Why |
|--------------|-----|
| Reasonix threshold / summary headings / adaptive numbers in `packages/ai\|agent` | ADR 0009 D-P32-2 — policy stays in package |
| New public hooks (`on_cache`, parallel payload/context APIs) | ADR 0009 D-P32-3 / feature §2.0 |
| Ordered / closed `enabled` load-plan machine | feature **Q21** v0.0.42: single payload mutator ⇒ constructive terminal |
| Tool repair / large tool_result shrink / flash-first (pillar **D**) | feature OUT |
| Runtime tool memo / `@realvendex/pi-cache` (pillar **F**) | feature OUT |
| TUI / CLI product / boot environment / npm / git / `~/.pi` | ADR 0006/0008 |
| P4 `competitive_app` workflow / settings product surface | roadmap serial order |
| Status tool / host diagnostics API / package config grammar | feature **N1** |

---

## 1. Binding constraints (contract for implementers)

| ID | Must |
|----|------|
| Feature v0.1.0 | Full locked set A/B/E + §2.0–§2.19 + §6 T1 — **no inventing open scope** |
| ADR 0009 | D-P32-1…D-P32-4 |
| ADR 0008 / 0006 | S-engine only; local packages only; no TUI / install |
| D5 / D16 / G3 | P3.2 stage; no second kernel; Reasonix policy not welded into core |
| Q21 | Closed first-party set; Reasonix sole payload mutator; `enabled` remains unordered whitelist; no runner priority/final; reload = new epoch |
| R1/P1/C1/X1 | `compactionPlan` variant on `session_before_compact`; host validates + summary + rewrite; single plan fail-closed |
| S1 | Isolated no-tools summary; no session id; no extension callbacks; mechanical fallback |
| V1 / R3 / I1 | Adapter cache parity; default short retention; caller/Session-owned identity only |
| T1 / §6 | Offline gates required; live opt-in only |
| N1 | One extension module; **zero tools** |

**Prerequisite check (gate G0):**

```bash
.venv/bin/pytest tests/packages/ai tests/packages/agent tests/capability_loader -m "not live" -q
```

P3.1 Offline + search offline suites remain green after each phase.

---

## 2. Work map (port vs host-delta vs package)

### 2.1 `packages/ai` — upstream cache parity (V1)

| Area | Responsibility | Feature anchor |
|------|----------------|----------------|
| OpenAI-compatible request | `prompt_cache_key` / retention wire; final `onPayload` once per HTTP attempt | §2.14 / §2.14a / callback parity |
| OpenAI-compatible usage | nested `prompt_tokens_details.cached_tokens`; DeepSeek top-level hit/miss/write → `Usage.cacheRead/cacheWrite` | §2.14 / §2.16 |
| Anthropic Messages request | `cache_control` on system/history/tools per upstream compat; retention | §2.14 / P1-M |
| Anthropic usage | `cache_read_input_tokens` / `cache_creation_input_tokens` (+ 1h split if present) | §2.14 |
| Stream callbacks | every real HTTP attempt: one final `onPayload`; one `onResponse({status,headers})` on any response (incl. non-2xx) | §2.14(5) |
| Unknown family | no invented controls; diagnostics only | §2.14 |

**Rule:** isomorphic to upstream `main`; no Reasonix-named APIs; no new `Usage.cacheMiss`.

### 2.2 `packages/agent` — generic CompactionPlan bridge

| Area | Responsibility | Feature anchor |
|------|----------------|----------------|
| `SessionBeforeCompactResult` variant | accept typed `compactionPlan` **without** breaking legacy `compaction?: CompactionResult` | §2.9 R1 |
| Plan validation | snapshot fingerprint; fold/retain partition; tool-call/result atomicity; active-turn retain | §2.10 P1 |
| Collision | cancel short-circuit; single plan only; multi-plan / plan+legacy fail-closed | §2.12 X1 |
| `ctx.compact()` | harness: register pending request only; bare Agent: still raise unavailable | §2.11 C1 |
| `ctx.getContextUsage()` | harness: recent provider usage + trailing context estimate (Pi semantics) | §2.8a T2 |
| `prepareNextTurn` checkpoint | after `turn_end`: serial before_compact → validate → S1 → rewrite → sync messages/context → `session_compact` | §2.11 C1 |
| S1 summary transport | current provider/model; no tools; strip session id; **no** extension callbacks; 90s + one non-deadline retry; mechanical fallback | §2.8 S1 |
| Harness hydration / resume | per-prompt + post-turn Session projection; metadata id → `session_id`; no re-append | §2.14c M3 / §2.14d R4 |
| Session identity | bare Agent caller-owned; harness `Session.getMetadata().id` | §2.14b I1 |
| Cache retention passthrough | `AgentOptions.cache_retention` → loop/stream options; default short | §2.14a R3 |

**Rule:** zero Reasonix policy strings/thresholds in core; no new public hook brands.

### 2.3 `capability_packages/reasonix_prefix_cache` — consumer policy

| Area | Responsibility | Feature anchor |
|------|----------------|----------------|
| Package layout | `package.json` + single `extensions/reasonix_prefix_cache.py` | §2.18 N1 |
| Events | `before_provider_request`, `session_before_compact`, `after_provider_response`, `message_end`, `turn_end`; recommended `session_start` / `context` / `session_compact` | §2.2 |
| A / P1 | active tools canonicalize for known shapes; marker same-value transfer only | §2.3 / P1-M |
| E1 epoch | first canonical outbound baseline; prefix_break + expected_cold; no fake miss | §2.4 |
| B plan | fold/retain/tail + fixed summary headings; small-user retain floor | §2.8d K1/K2-R |
| T2 / W2a / L1 | turn_end threshold; adaptive small window; stuck guard | §2.8a–e |
| E metrics | read-only `message_end` usage; namespace/epoch buckets; reuse ratio | §2.16 |
| Reload | new runner attachment ⇒ fresh epoch; no cross-runner metrics | Q21g |
| Tools | **none** | N1 |

### 2.4 Explicit omit

| Item | Status |
|------|--------|
| Ordered `enabled` load plan / loader admission gate / public order hook | **omit** (Q21) |
| `reasonix_cache_status` tool / host diagnostics API | **omit** (N1) |
| Package JSON/YAML/env tuning surface | **omit** |
| Pillars C / D / F | **omit** |
| Coding-agent Files/Commands summary columns | **omit** (K1) |
| Second Session / JSONL format / tree product | **omit** (M3) |
| npm / git / home discovery / TUI | **omit** |

---

## 3. Target layout

```text
packages/ai/src/earendil_works/pi_ai/
  api/…                     # V1 cache request + usage parse + onPayload/onResponse parity
  providers/…               # only if upstream parity requires
  types.py                  # existing Usage/CacheRetention — no Reasonix fields

packages/agent/src/earendil_works/pi_agent/
  extensions/types.py       # SessionBeforeCompactResult + CompactionPlan variant (P3.2 delta)
  extensions/runner.py      # merge rules for plan / cancel / X1 (if needed)
  agent.py                  # bind getContextUsage / compact when harness-backed
  harness/
    agent_harness.py        # prepareNextTurn checkpoint; compact registration; hydration R4
    compaction/…            # validate plan; S1 summary; atomic rewrite; mechanical fallback

capability_packages/
  reasonix_prefix_cache/
    package.json
    extensions/
      reasonix_prefix_cache.py

docs/
  features/
    reasonix_prefix_cache_v1.md          # frozen v0.1.0
    agent_engine_extensions_v1.md        # P3.2 delta version bump (D0)
  plans/
    P3_2_pi_extension_capability_enablement.md   # this file
    P3_1_agent_engine_extensions.md              # versioned delta note (D0)

tests/
  packages/ai/
    unit|integration/faux/…              # V1 request/usage/callback fixtures
  packages/agent/
    unit/…                               # plan validation, X1, S1 isolation
    integration/faux/…                   # checkpoint rewrite, re-entry, L1, resume
  capability_loader/
    integration/faux/…                   # reasonix E2E + reasonix+search co-load
    integration/live/…                   # opt-in warm-cache smoke
```

### 3.1 Package convention

```python
# capability_packages/reasonix_prefix_cache/extensions/reasonix_prefix_cache.py
def register(api) -> None:
    api.on("session_start", on_session_start)
    api.on("before_provider_request", on_before_provider_request)
    api.on("after_provider_response", on_after_provider_response)
    api.on("message_end", on_message_end)          # must return None
    api.on("turn_end", on_turn_end)                # must return None
    api.on("session_before_compact", on_before_compact)
    api.on("session_compact", on_session_compact)
    api.on("context", on_context)                  # optional read-only
    # no register_tool
```

### 3.2 Attach path (unchanged AP3; unordered enable)

```python
report = await load_capability_packages(
    root,
    enabled=["reasonix_prefix_cache", "search_tavily"],  # set/whitelist; order NOT semantic
)
attach_extension_runtime(agent, …)  # or apply_capability_report thin path
# Reasonix is sole payload mutator ⇒ constructive terminal (feature Q21)
```

---

## 4. Status board (update as you go)

Status: `todo` | `in_progress` | `done` | `blocked`.

| Step | Phase | Status | Note |
|------|-------|--------|------|
| G0 | P1–P3.1 + search offline green | **done** | 2026-07-26: `124 passed, 25 deselected` (`-m "not live"`) |
| D0 | Docs gate: freeze already done; extension feature P3.2 delta + P3.1 plan delta | **done** | feature v0.3.0；P3.1 plan v0.2.4 remains completed |
| A1 | OpenAI-compatible cache request + usage fixtures | **done** | request key/retention + nested/DeepSeek usage fixtures |
| A2 | Anthropic Messages cache_control + usage fixtures | **done** | system/history/tools markers + read/write/1h usage |
| A3 | onPayload / onResponse once-per-attempt parity both families | **todo** | §2.14(5) |
| A4 | cacheRetention default short + generic none/short/long passthrough | **todo** | R3 |
| B1 | CompactionPlan types + `session_before_compact` variant (keep legacy) | **todo** | R1 |
| B2 | Host plan validation (fingerprint / partition / tool pairing) | **todo** | P1 |
| B3 | X1 collision: cancel / single plan / fail-closed | **todo** | X1 |
| B4 | S1 isolated summary + retry + mechanical fallback | **todo** | S1 |
| B5 | prepareNextTurn checkpoint + atomic rewrite + session_compact | **todo** | C1 |
| B6 | bind `getContextUsage` + `compact` on harness path | **todo** | T2 host half |
| B7 | Harness hydration / resume R4 + session id I1 | **todo** | M3/R4/I1 |
| C1 | Scaffold `capability_packages/reasonix_prefix_cache` | **todo** | N1 |
| C2 | A path: P1 canonicalize + E1 epoch + fingerprint diagnostics | **todo** | §2.3–2.4 |
| C3 | E path: message_end metrics buckets + after_provider_response headers | **todo** | §2.16 |
| C4 | B path: turn_end T2/W2a/L1 + session_before_compact plan (K1/K2-R) | **todo** | §2.8* |
| C5 | Offline extension E2E (deterministic cache server) | **todo** | §2.17(2) |
| C6 | Offline compaction + resume gates | **todo** | §2.17(3) / §2.14d |
| C7 | Reasonix + search co-load gate (no tool/lifecycle collision) | **todo** | ADR 0009 D-P32-4(4) |
| C8 | Live opt-in full-stack warm-cache smoke（正式 loader/Harness 路径；第 2 请求 `cacheRead > 0` 且进入 E1） | **todo** | §2.17(4); ordinary CI may skip, P3.2 close requires recorded green run |
| C9 | Plan status completed；roadmap P3.2=done | **todo** | exit |

**Rules:**

- Do not start B* until A1–A3 fixtures prove usage/callback bytes (B can draft types earlier, but rewrite gates need real usage for E).
- Do not start C* package policy until B5/B6 make `ctx.compact()` / plan path real on harness.
- Do not mark P3.2 done without **C5+C6+C7** offline green and one explicitly configured **C8 green** run; ordinary credential-less CI may skip C8, but a skip is not P3.2 completion evidence.
- Do not introduce ordered load-plan parameters or public extension order APIs.
- Do not put Reasonix thresholds/headings into `packages/ai|agent`.
- Do not register any Reasonix tool.

---

## 5. Phased implementation steps

### Phase D — Docs gate (before code that depends on extension surface)

**D0. Versioned deltas (ADR 0009 D-P32-4)**

1. Bump `agent_engine_extensions_v1` feature contract with P3.2 delta:
   - `compactionPlan` on `SessionBeforeCompactResult`
   - C1 harness binding semantics for `compact` / `getContextUsage`
   - X1 single-plan fail-closed
   - keep legacy `compaction` result path
2. Add a short **P3.2 delta** section/changelog entry on `P3_1_agent_engine_extensions.md` pointing at this plan (P3.1 remains **completed** baseline; not reopened as unfinished).
3. Confirm roadmap §2 P3.2 + §5 status board reference this plan.

### Phase A — `packages/ai` cache parity

**A1. OpenAI-compatible**

- Request: wire cache key / retention per upstream.
- Usage: parse nested + DeepSeek top-level shapes into existing `Usage` fields.
- Tests: deterministic fixtures for request shape + usage mapping.

**A2. Anthropic Messages**

- Request: `cache_control` placement + retention compat.
- Usage: read/write (+ 1h if present) → `Usage`.
- Tests: fixtures including tool-marker boundary used by package P1-M.

**A3. Callback parity**

- Each HTTP attempt: exactly one final `onPayload` (send returned payload).
- On any HTTP response: exactly one `onResponse`.
- No silent bypass on either active family.

**A4. Retention resolution**

- Default `short` when unspecified.
- Honor generic `none` / `short` / `long`.
- `PI_CACHE_RETENTION=long` remains ai-level legacy compat only — **not** Reasonix package config.

### Phase B — `packages/agent` generic bridge

**B1. Types**

- `CompactionPlan` fields per §2.10 (`version`, `snapshotFingerprint`, `foldEntryIds`, `retainEntryIds`, `summaryInstructions`, `details`).
- Extend before-compact result merge to carry plan variant.

**B2–B3. Validate + collide**

- Implement host validation; diagnostics on failure; no rewrite.
- X1 rules in runner/harness merge.

**B4. S1 summary**

- Isolated simple completion: model/key/static headers/retention from current agent config.
- Strip session identity + tools; **skip all extension callbacks**.
- 90s deadline; one non-deadline retry; mechanical fallback template deterministic.

**B5. Checkpoint rewrite**

- `prepareNextTurn`: pending compact → emit before → validate → summary → append compaction entry → rebuild Session context → sync Agent + loop context → emit `session_compact`.
- At most one in-flight transaction; re-entry coalesces.

**B6. Context bindings**

- Harness `bind_core`: real `getContextUsage`, real `compact` (register only).
- Bare Agent: keep explicit unavailable / None behavior (A/E ok; B not claimed).

**B7. Hydration / identity**

- Per `AgentHarness.prompt` and post-turn: `Session.build_context` + metadata id.
- Never re-append restored history.
- No synthesized UUID identity.

### Phase C — Reasonix package + gates

**C1. Scaffold** package per §2.18.

**C2–C4. Policy handlers** implementing A/B/E only as locked.

**C5. Offline E2E** — deterministic cache server keyed on equal cacheable prefix of actual outbound payload.

**C6. Offline compaction + resume** — plan/retry/fallback/re-entry/L1; JSONL reopen first outbound uses rebuilt transcript + metadata id.

**C7. Co-load** — `reasonix_prefix_cache` + at least one search package:
- no tool name collision (Reasonix has zero tools)
- search tools still callable
- Reasonix still sole payload mutator / constructive terminal
- no lifecycle handler conflict on shared events

**C8. Live opt-in full-stack warm-cache proof** — one explicitly configured V1 cache-capable provider. This is a release/close gate, not a direct `Models.stream*` adapter probe:

1. Load `reasonix_prefix_cache` through `load_capability_packages`; assert no load error and zero registered tools.
2. Attach the returned capability report through the production apply/attach path to an `AgentHarness` backed by a real `Session`, the configured real provider/model, and the normal `packages/ai` adapter. Directly calling `Models.stream*` without the package, extension runner, and Harness does **not** satisfy C8.
3. Use one Harness/Session and one unique test-run cache namespace. Send two turns whose provider-defined cacheable prefix is long enough and identical, while allowing only an append-only suffix. Keep provider, model, credentials, cache retention, tools, system prompt, and session identity unchanged between requests.
4. Capture only structural evidence from the final outbound payload callback: cacheable-prefix digest/length, provider family, model id, and callback counts. Assert the two cacheable-prefix digests are equal and that each real HTTP attempt emits one final payload callback and one response callback. Never persist payload bodies, headers containing credentials, or secrets.
5. The first request must complete successfully and establish the baseline. If the provider exposes cache-write usage, assert `cacheWrite > 0`; otherwise record it as unavailable rather than fabricating a write/miss assertion.
6. The second request must complete successfully and expose `Usage.cacheRead > 0` on the real assistant message. Assert the same usage reaches Reasonix through `message_end` and increments the current namespace/epoch E1 cache-read bucket; use in-process test observation only—do not add a status tool or public diagnostics API.
7. Assert there is no Agent/Harness error, no unexpected epoch break between the two stable-prefix requests, and no secret-bearing test output. Do not add retries or extra warm-up requests that could hide failure of the required second request.
8. Record sanitized close evidence: test command, provider family, model id, timestamp, pass result, first/second cache read/write counts when available, and cacheable-prefix digest/length. Credentials, raw prompts, raw payloads, and response bodies are forbidden.

Ordinary CI skips C8 unless explicit live opt-in and credentials are present. A configured failure means that environment has not proved the feature. A credential-less skip keeps ordinary CI green but **cannot** be used to close C8 or mark P3.2 completed.

**Scope of this proof:** C8 proves the real warm-cache path `local loader → Reasonix extension → AgentHarness/Session → packages/agent → packages/ai adapter → provider → Usage → message_end/E1`. Deterministic C5/C6 remain the normative proof for compaction validation, retry/fallback, atomic rewrite, re-entry, and resume; C8 must not be described as live proof of those branches.

**C9. Close** plan + roadmap P3.2=done only after the offline matrix and recorded C8 run are green.

---

## 6. Acceptance matrix (normative = feature §6 / §2.17)

| Gate | Must prove | Suite |
|------|------------|-------|
| Offline adapter | §2.17(1) OpenAI-compatible + Anthropic request/usage + callback once-each + P1 stable tools order/marker | `tests/packages/ai` |
| Offline extension E2E | §2.17(2) prefix equality → cacheRead; break → expected_cold not fake miss; E1 buckets | `tests/capability_loader` + agent faux |
| Offline compaction | §2.17(3) plan validate; S1 isolation; rewrite; re-entry; L1; mechanical fallback bytes | `tests/packages/agent` |
| Offline resume | §2.14d JSONL reopen; metadata id; no duplicate append | `tests/packages/agent` harness |
| Co-load | ADR 0009 D-P32-4(4) Reasonix + search | `tests/capability_loader` |
| Live opt-in | §2.17(4) full-stack official path: package loads with zero tools; stable cacheable-prefix digest; second real response `cacheRead > 0`; usage reaches `message_end` / current E1 bucket; sanitized evidence recorded | `pytest.mark.live` |

Ordinary CI = all offline gates and may skip unconfigured Live. P3.2 close additionally requires one explicitly configured C8 green run; a skip is not close evidence.

---

## 7. Exit criteria

P3.2 is **done** only when:

1. Feature v0.1.0 remains frozen; no silent scope expansion.
2. D0 extension-contract delta published.
3. Offline matrix above green.
4. One explicitly configured full-stack Live C8 run is green and its sanitized evidence is recorded; ordinary credential-less CI may skip C8, but P3.2 remains unclosed until this evidence exists.
5. ADR 0006/0008 omit still true (no install/TUI/second kernel/new public hook brand).
6. No Reasonix policy constants in `packages/ai|agent`.
7. Roadmap §5 marks P3.2 **done**; this plan status **completed**.

---

## 8. Implementation notes (non-normative, for agents)

1. **Constructive terminal (Q21):** do not change `LocalPackageManager.enabled` to ordered list; keep set/whitelist + `sorted(by name)` discovery. Document in tests that Reasonix is the only `before_provider_request` mutator in the v1 first-party set.
2. **Legacy compact path:** harness today may treat `before["compaction"]` as finished result — keep that path; add plan variant beside it (feature §2.9(4)).
3. **Summary must not touch E:** assert in tests that summary completion does not emit extension events and does not move epoch/metrics.
4. **Upstream first:** when ai cache behavior is ambiguous, re-read `earendil-works/pi` `main` and port; do not invent Reasonix-specific wire formats in core.
5. **codegraph:** after large file landings, `codegraph sync`.

---

## 9. Changelog

| Version | Date | Notes |
|---------|------|-------|
| 0.1.1 | 2026-07-26 | Tighten C8 into a full-stack close gate: official loader/Harness path, stable-prefix provenance, real Usage → E1 propagation, sanitized evidence, and no completion by skip. |
| 0.1.0 | 2026-07-26 | Initial plan after feature **v0.1.0 freeze**; three-phase A/B/C + D0 docs gate; Q21 closed native-set (no ordered load plan); maps feature §6 T1 + ADR 0009. |
