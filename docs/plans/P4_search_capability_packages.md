# Plan: P4 — Search capability packages v1

| Field | Value |
|-------|--------|
| **plan_id** | `P4-search-capability-packages` |
| **plan_version** | `0.1.2` |
| **status** | **completed** |
| **created** | 2026-07-23 |
| **updated** | 2026-07-23 |
| **roadmap** | [`docs/ROADMAP.md`](../ROADMAP.md) — 业务能力 v1 / search capability |
| **contract** | [`docs/contracts/ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.3** |
| **feature** | [`docs/features/search_capability_packages_v1.md`](../features/search_capability_packages_v1.md) **v0.1.11 frozen** — `search-capability-packages-v1` (F-S1…F-S18 + §10) |
| **ADR** | [0006 local package subset](../contracts/adr/0006-package-manager-local-isomorphic-subset.md) · [0007 legacy repo](../contracts/adr/0007-legacy-repo-capability-reference.md) |
| **depends_on** | **P3 done** — [`P3_capability_loader.md`](P3_capability_loader.md); feature contract frozen |
| **reference** | 旧仓 `competitive-agent` (Tavily/AnySearch) · [GuDaStudio/GrokSearch](https://github.com/GuDaStudio/GrokSearch) `grok-with-tavily` (Grok search only) |
| **target** | `capability_packages/search_{tavily,anysearch,grok}/` → Pi `AgentTool` via existing loader |
| **tests** | `tests/capability_loader/` (unit / contract / integration/faux / integration/live) |
| **non_goal** | Full P4 `competitive_app` workflow / report schema / provider router |

---

## 0. Purpose

1. Implement the **frozen** search capability boundary in `docs/features/search_capability_packages_v1.md` v0.1.11 as three local Pi packages.
2. Register **five** provider-prefixed `AgentTool`s through the existing P3 package-manager path (no MCP host, no second runtime).
3. Prove offline O1–O6 and live L1–L4 (agent can call tools; results visible in `toolResult`).
4. Leave P4 Application workflow, evidence IDs, and report DAG to a **later** plan.

**Approach:** thin in-process HTTP adapters + `register(api)` extensions (FEATURES F-S1, F-S17). Not a port of old-repo MCP/package runtime.

---

## 1. Binding constraints (contract for implementers)

| ID | Must |
|----|------|
| Feature F-S1…F-S18 | Full locked decision set; **no inventing open scope** |
| Feature §10 | Offline O1–O6 + Live L1–L4 are the exit gates |
| D5 / D22 / G5 | Local `capability_packages/*` only; Python packages; no remote install |
| D12 / ADR 0007 | Old repo = capability **reference** only |
| G3 / G7 | No second agent kernel; packages ↛ `competitive_app.domain` |
| G10 | No MCP adapter product path; no `mcp_package` type |
| D23 | Search **provider** config = env only; package enablement = P4 settings whitelist (when app exists) |
| P3 | Use `load_capability_packages` / `apply_capability_report` as-is; do not fork loader for this feature |

**Prerequisite check (gate G0):**

```bash
.venv/bin/pytest tests/packages/ai tests/packages/agent tests/capability_loader -m "not live" -q
```

P3 `echo_example` path remains green.

---

## 2. Reference map (not upstream port)

This plan is **not** a TS→Python isomorphic port. Sources are **behavior references** only.

### 2.1 Capability surface (normative = feature contract)

| Package | Tools | Env (required) |
|---------|-------|----------------|
| `search_tavily` | `tavily_search`, `tavily_fetch` | `TAVILY_API_KEY` (`TAVILY_API_URL` default ok) |
| `search_anysearch` | `anysearch_search`, `anysearch_fetch` | `ANYSEARCH_API_KEY`, `ANYSEARCH_API_URL` |
| `search_grok` | `grok_search` | `GROK_API_KEY`, `GROK_API_URL`, `GROK_MODEL` |

Result envelopes: `search_result.v1` / `fetch_result.v1` (feature contract §6–§8).  
`canonical_url == url` always. Full fetch body; no local URL SSRF stack.  
HTTP timeout: `connect=6, write=10, read=120`. Grok only: bounded retries (max 3). Abort via Pi `AbortSignal`.

### 2.2 Reference locations

| Area | Look at | Do **not** take |
|------|---------|-----------------|
| Tavily REST shapes / hit fields | 旧仓 `package_bundles/search_tavily/server.py` | FastMCP server, workflow IDs |
| AnySearch normalize / MCP client shape | 旧仓 `package_bundles/search_anysearch/server.py` | Old package runtime, SafeNetworkClient as product path |
| Grok search + answer/sources | GrokSearch `providers/grok.py`, source split helpers | `web_fetch`/`web_map`, session_id cache, `get_sources`, Firecrawl |
| Tool registration | `capability_packages/echo_example` | — |
| Load path | `earendil_works.pi_agent.package_manager` | New loader types |

### 2.3 Explicit omit

| Item | Status |
|------|--------|
| Old `search.core` / collector orchestration | **omit** |
| Unified `web_search` / router package | **omit** |
| `grok_fetch` / `grok_get_sources` | **omit** |
| Vendor/submodule GrokSearch or old MCP trees | **omit** |
| `tenacity` / generic Tool retry in Pi core | **omit** |
| Local `SafeNetworkClient` / DNS pin for fetch | **omit** (F-S15) |
| P4 research stages / evidence IDs / reports | **omit** (later plan) |
| Changes to `packages/ai|agent` public API for search types | **omit** |

---

## 3. Target layout

```text
capability_packages/
  search_tavily/
    package.json
    extensions/
      tavily_tools.py          # register(api) → two AgentTools
  search_anysearch/
    package.json
    extensions/
      anysearch_tools.py
  search_grok/
    package.json
    extensions/
      grok_tools.py

# Shared helpers: DO NOT add capability_packages/_search_common/ (or any extra
# immediate child). LocalPackageManager treats every non-dot child dir as a
# package. Prefer per-package private helpers only (e.g. extensions/_normalize.py).

tests/capability_loader/
  unit/search_*.py             # normalize, schema, missing env
  contract/search_*.py         # tool names, no domain imports, no mcp_package
  integration/faux/test_search_*.py
  integration/live/test_search_*.py
  fixtures/search/             # provider JSON fixtures

config/settings.example.yaml   # capability_packages.enabled whitelist (when wiring)
.env.example                   # empty TAVILY_*/ANYSEARCH_*/GROK_* placeholders
docs/plans/P4_search_capability_packages.md
```

### 3.1 Extension convention

Match `echo_example`:

```json
{
  "name": "search_tavily",
  "version": "0.1.0",
  "keywords": ["pi-package"],
  "pi": {
    "extensions": ["./extensions"]
  }
}
```

```python
def register(api) -> None:
    # validate env → raise sanitized error if incomplete
    api.add_tool(AgentTool(name="tavily_search", ...))
    api.add_tool(AgentTool(name="tavily_fetch", ...))
```

### 3.2 AgentToolResult shape (all tools)

```python
payload = { ... search_result.v1 | fetch_result.v1 ... }
return {
    "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
    "details": payload,
}
```

Hard failures: raise exception → agent loop `isError=true`.  
Empty search hits: success with `hits=[]`. Partial: keep good rows + `warnings`.

### 3.3 HTTP

```python
async with httpx.AsyncClient(
    timeout=httpx.Timeout(connect=6.0, write=10.0, read=120.0, pool=None),
) as client:
    ...
```

- Tavily / AnySearch: **one** request per tool call (no auto-retry).
- Grok: source-aligned bounded retries; stop after first stream chunk; honor `Retry-After` on 429.
- Check `signal.aborted` before request / between Grok retries; cancel in-flight HTTP on abort.

---

## 4. Status board

| Step | Phase | Status | Note |
|------|-------|--------|------|
| G0 | P1–P3 offline green | done | offline suite green |
| A0 | Plan + feature contract cross-link | done | path: docs/features/… |
| A1 | Scaffold three packages + package.json | done | fail-closed without env |
| A2 | Per-package private helpers only | done | no extra package-root dir |
| B1 | `search_tavily` search + fetch | done | mockable httpx |
| B2 | `search_anysearch` search + fetch | done | minimal streamable-HTTP MCP client inside extension |
| B3 | `search_grok` search only | done | answer+hits one shot |
| B4 | Missing-env → diagnostic, zero tools | done | F-S11 |
| C0 | Contract: tool names, no domain, no mcp package type | done | |
| C1 | Offline O1–O6 (unit + mock + faux agent) | done | **exit offline** |
| C2 | Live L1–L4 with real `.env` keys | done | Tavily / AnySearch / Grok live green |
| C3 | settings.example whitelist + docs status | done | |
| C4 | Plan completed; roadmap note | done | |

---

## 5. Phased steps

### Phase A — Scaffold

1. Create three package dirs under `capability_packages/` with valid `package.json`.
2. Stub `register(api)` that fails closed without env (or no-ops until B — prefer fail-closed).
3. Confirm `load_capability_packages(enabled=[...])` discovers package names.
4. Ensure `.env.example` has empty search keys (already partially done).

### Phase B — Adapters

**B1 Tavily**

- `POST {TAVILY_API_URL}/search` and extract API as per public Tavily + old-repo field mapping.
- Normalize → `search_result.v1` / `fetch_result.v1`.
- Inputs: feature contract §4.1 curated params only; `additionalProperties: false`.

**B2 AnySearch**

- Use `ANYSEARCH_API_URL` + key; prefer REST if available; if only streamable HTTP MCP endpoint exists, keep a **minimal in-process client** inside the extension (still not a Pi MCP package type).
- Same result envelopes and fail/warning rules.

**B3 Grok**

- OpenAI-compatible chat completions stream against `GROK_API_URL` + `GROK_MODEL`.
- Split answer + sources in one response; no `session_id` / process cache.
- Bounded retries only for this adapter.

**B4 Config gate**

- Before `add_tool`, validate required env; raise sanitized errors on missing keys.
- Default non-strict load: other packages still load.

### Phase C — Exit

- **C1:** Offline suite maps 1:1 to feature contract §10.1 O1–O6.
- **C2:** Live tests: scripted toolCall (or small model) + real HTTP; assert non-empty content in `toolResult`.
- **C3:** Document enable list in `config/settings.example.yaml` for future P4 wiring.
- **C4:** Mark this plan completed; update roadmap board note if search capability slice is done (full P4 app still separate).

Public load path (normative, already exists):

```python
report = await load_capability_packages(
    enabled=["search_tavily", "search_anysearch", "search_grok"],
)
apply_capability_report(agent, report)
```

---

## 6. Test strategy

| Layer | Assert | Feature §10 |
|-------|--------|----------|
| Unit normalize | fixtures → v1 envelopes; `canonical_url == url`; warnings | O4 |
| Unit config | missing env → register raises; loader diagnostic; zero tools | O2 |
| Contract | tool name set exact; no `competitive_app` imports; no install/MCP package type | O1, omit |
| Unit/mock HTTP | five tools success + hard failure → exception | O5 |
| Integration faux | Agent + faux model toolCall → `toolResult` JSON visible | O6 |
| Live | real keys; at least one search (+ fetch if configured); non-empty content | L1–L4 |

```bash
# offline (default CI)
.venv/bin/pytest tests/capability_loader -m "not live" -q

# live (local / secret CI)
.venv/bin/pytest tests/capability_loader/integration/live -m live -q
```

Live env (gitignored `.env`): `TAVILY_*`, `ANYSEARCH_*`, `GROK_*` as feature contract §4.2. Unconfigured provider → **skip**, not fail.

---

## 7. Risks

| Risk | Mitigation |
|------|------------|
| AnySearch only exposes MCP transport | Keep client **inside** extension; exterior remains AgentTool; no Pi MCP product |
| Grok gateway is `openai-responses` not chat completions | Smoke early in C2; adjust path only within `search_grok` if needed, document host delta in plan revision |
| Full fetch body blows context | Accepted by F-S6; do not reintroduce truncation without feature contract change |
| Shared helper becomes mini-framework | Per-package only; no `capability_packages/*_common` root |
| Scope creep into research workflow | Explicit non-goal; refuse evidence_id / stages in packages |

---

## 8. Definition of done

- [x] Three packages load via whitelist; five tool names only
- [x] Missing env → package contributes zero tools + error diagnostic
- [x] Result contracts match feature contract §6–§8 (including `warnings`)
- [x] Offline O1–O6 green
- [x] Live L2–L3 pass for every fully configured provider in local `.env`
- [x] No changes required to architecture contract / no new ADR (unless scope expands)
- [x] This plan status → **completed**; roadmap search-capability note updated

---

## 9. Revision log

| Version | Date | Note |
|---------|------|------|
| 0.1.0 | 2026-07-23 | Initial plan from FEATURES v0.1.11 frozen; implement-only after env prepared |
| 0.1.1 | 2026-07-23 | Feature SoT → `docs/features/search_capability_packages_v1.md`; forbid extra package-root dirs; conflict audit |
| 0.1.2 | 2026-07-23 | Implemented three packages / five tools; offline O1–O6 + live L1–L4 green |
