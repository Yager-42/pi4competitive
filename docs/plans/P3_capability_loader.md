# Plan: P3 — Local isomorphic subset of coding-agent package-manager

| Field | Value |
|-------|--------|
| **plan_id** | `P3-capability-loader` |
| **plan_version** | `0.2.0` |
| **status** | **completed** |
| **created** | 2026-07-23 |
| **updated** | 2026-07-23 |
| **roadmap** | [`docs/ROADMAP.md`](../ROADMAP.md) stage **P3** |
| **contract** | [`docs/contracts/ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.2** |
| **ADR** | [0004 local-only](../contracts/adr/0004-local-capability-packages-only.md) + **[0006 isomorphic local subset](../contracts/adr/0006-package-manager-local-isomorphic-subset.md)** |
| **depends_on** | **P2 done** — [`P2_packages_agent.md`](P2_packages_agent.md) |
| **upstream** | `earendil-works/pi` **`main`** → `packages/coding-agent` **local subset only** |
| **upstream_snapshot** | same pin as ai/agent — see `UPSTREAM_SHA.txt` (include coding-agent sparse) |
| **target** | `earendil_works.pi_agent.package_manager` (+ resource load) → feed `AgentTool` / skills into P2 Agent |
| **tests** | `tests/capability_loader/` (name kept) + contract omit-list |

---

## 0. Purpose

1. **Port** the **local-only subset** of coding-agent package discovery & resource resolution isomorphically (TS→Python).
2. **Omit** install / npm / git / home / CLI entirely (ADR 0006 D-PM3).
3. Wire resolved resources into **existing P2** `Agent` / harness (no second loop).
4. Ship **`capability_packages/echo_example`** + C1: load → Agent(faux) tool call.

**Approach:** **A** (isomorphic subset), not thin greenfield-only loader.

---

## 1. Binding constraints

| ID | Must |
|----|------|
| D5 / D22 | Local only; root **`capability_packages/`**; no remote; no `~/.pi` default |
| **ADR 0006** | Coding-agent **local subset isomorphic**; install surfaces omitted |
| D4 / G4 | Mappable module boundaries to coding-agent sources listed in §2 |
| D16 / G8 | After P2; before P4 |
| G3 | Loader lives under `pi_agent` extension; **not** a second agent kernel |
| G5 | Capability packages Python-only |
| G7 | Packages ↛ `competitive_app` |
| G10 | No download default path |
| P2 | Tool **execution** = `AgentTool` + agent loop already ported |

**G0:**

```bash
.venv/bin/pytest tests/packages/ai tests/packages/agent -m "not live" -q
```

---

## 2. Upstream module map (port vs omit)

Re-fetch: `scripts/fetch_upstream.sh` sparse paths must include `packages/coding-agent` (at least `src/core/package-manager.ts`, `resource-loader.ts`, `extensions/loader.ts`, `skills.ts`, `prompt-templates.ts`, `docs/packages.md`).

### 2.1 Port (local subset)

| Upstream | Python target (expected) | Responsibility |
|----------|--------------------------|----------------|
| `coding-agent/src/core/package-manager.ts` — types `PathMetadata`, `ResolvedResource`, `ResolvedPaths` | `package_manager/types.py` | Shared shapes |
| `…/package-manager.ts` — local collect helpers (`collectFiles`, skill/prompt/extension discovery, pi manifest, filters) | `package_manager/discover.py` / `collect.py` | **Local** resource enumeration |
| `…/package-manager.ts` — `resolve` **local path packages only** | `package_manager/package_manager.py` → `LocalPackageManager` | Resolve under `capability_packages/` |
| `…/resource-loader.ts` — load skills/prompts/extensions from resolved paths | `package_manager/resource_loader.py` | Load into runtime objects |
| `…/extensions/loader.ts` — load extension modules | `package_manager/extensions_loader.py` | **Host delta:** Python import → tools |
| `…/skills.ts` / prompt loading | reuse `harness/skills.py` + `prompt_templates.py` where possible | File semantics |
| `docs/packages.md` — Package Structure / Filtering (local) | `capability_packages/README.md` | Human convention |

### 2.2 Explicit omit (must not ship)

| Upstream | Status |
|----------|--------|
| `PackageManager.install` / `installAndPersist` / `remove*` / `update` / `checkForAvailableUpdates` | **omit** |
| npm / git source parse & clone & `npm install` | **omit** |
| `package-manager-cli.ts` | **omit** |
| user `agentDir` / `~/.pi` auto paths | **omit** |
| temporary extension install folder | **omit** |
| themes / TUI theme loading | **omit** or stub host-delta |
| settings dual-scope package install persistence | **omit** (use enabled whitelist) |
| `MissingSourceAction: "install"` | **omit** |

Contract tests must fail if install/npm/git clone helpers appear in loader code.

### 2.3 Default roots (host policy)

| Upstream concept | CompetitorLens |
|------------------|----------------|
| settings `packages: ["./path"]` + auto dirs | **Always** scan `capability_packages/*` children as local packages |
| optional filters | `enabled` / `disabled` package dir names; optional per-resource filters later |
| project vs user scope | Single scope: **repo local** |

---

## 3. Target layout

```text
packages/agent/src/earendil_works/pi_agent/
  package_manager/
    __init__.py                 # load_capability_packages, LocalPackageManager, …
    types.py                    # PathMetadata, ResolvedResource, ResolvedPaths, LoadReport
    package_manager.py          # LocalPackageManager.resolve (local only)
    collect.py                  # collectFiles, conventions, pi manifest
    resource_loader.py          # LocalResourceLoader
    extensions_loader.py        # Python extension → AgentTool registration
    apply.py                    # apply to Agent / Harness
    errors.py

capability_packages/
  README.md
  echo_example/
    package.json                # optional "pi" manifest (aligned)
    extensions/                 # or register.py Python host convention
      echo_tools.py
    # optional skills/ prompts/

docs/plans/P3_module_map.md
tests/capability_loader/
  contract/   # omit-list + layout + no domain
  unit/       # collect, resolve, filters
  integration/faux/
  fixtures/   # good package, bad package, manifest package
```

### 3.1 Extension host convention (Python)

Upstream loads `.ts` extensions via jiti. **Host delta:**

**Preferred package shapes (both allowed):**

1. **Upstream-like:** `extensions/**/*.py` exporting `register(api)` or tools list factory.  
2. **Minimal:** package root `register.py` with `register(api)` (still discovered as one local package).

`CapabilityRegisterApi` (same as before): `add_tool`, optional `add_skill` / `add_prompt_template`.

---

## 4. Status board

| Step | Phase | Status | Note |
|------|-------|--------|------|
| G0 | P1+P2 offline green | done | suite still green with P3 tests |
| A0 | Sparse vendor coding-agent + SHA note | done | UPSTREAM_SHA + vendor present |
| A1 | Scaffold `package_manager/` + `capability_packages/` | done | under `pi_agent.package_manager` |
| A2 | `P3_module_map.md` from §2 | done | |
| A3 | `capability_packages/README.md` (local structure only) | done | |
| B1 | Types + collect/discover (manifest + conventions) | done | |
| B2 | `LocalPackageManager.resolve` local-only | done | install methods raise UnsupportedInstallError |
| B3 | `LocalResourceLoader` skills/prompts/extensions load | done | |
| B4 | extensions_loader → `AgentTool[]` | done | host-delta Python register |
| B5 | `apply` to Agent; name collision policy | done | first_wins default |
| B6 | `echo_example` package | done | |
| C0 | Contract: omit install/npm/git; no domain; map closed | done | |
| C1 | faux Agent calls capability tool | done | **exit** |
| C2 | optional live `.env` | done | tests/capability_loader/integration/live/ |
| C3 | Roadmap P3=done; plan completed | done | |

---

## 5. Phased steps

### Phase A — Pin & scaffold

1. Extend `scripts/fetch_upstream.sh` default sparse: `ai agent coding-agent` (or coding-agent/src/core subset).  
2. Append coding-agent note to `UPSTREAM_SHA.txt`.  
3. Scaffold Python package tree §3.  
4. Write `P3_module_map.md`.

### Phase B — Port subset

**B1–B2:** Port pure discovery/resolve for directories under `capability_packages/`.  
Each child dir = one local package source (identity = resolved path).

**B3–B4:** Load files → Python objects / tools. Failures → diagnostics list (align ResourceDiagnostic intent).

**B5–B6:** Wire Agent + example package.

Public API (normative):

```python
def load_capability_packages(
    root: Path | None = None,
    *,
    enabled: list[str] | None = None,
    disabled: list[str] | None = None,
    strict: bool = False,
) -> LoadReport: ...

class LocalPackageManager:
    async def resolve(self) -> ResolvedPaths: ...
    # install/update/remove: NOT implemented
```

### Phase C — Exit

- **C1:** resolve echo_example → tools → Agent(faux) toolResult.  
- **C0:** grep/AST: no `npm install`, `git clone`, `homedir` package roots in package_manager package.  
- P1+P2 suite still green.

---

## 6. Test strategy

| Layer | Assert |
|-------|--------|
| Unit collect | manifest paths, convention dirs, filters |
| Unit resolve | only under capability_packages; skip bad pkgs |
| Contract omit | install/npm/git surfaces absent |
| Integration faux | end-to-end tool call |
| Live optional | gateway + echo package |

```bash
.venv/bin/pytest tests/packages/ai tests/packages/agent tests/capability_loader -m "not live" -q
```

---

## 7. Risks

| Risk | Mitigation |
|------|------------|
| Porting too much of 2650-line file | Strict §2.2 omit list; implement resolve path only |
| jiti semantics | Document host-delta; Python register API |
| Drift from thin-loader plan | This v0.2.0 supersedes v0.1.0 approach B |

---

## 8. Definition of done

- [x] Module map: every Port row done or host-delta  
- [x] No install/npm/git in shipped loader  
- [x] `capability_packages/echo_example` works with Agent(faux)  
- [x] C0+C1 green; P1+P2 still green  
- [x] Roadmap P3=done  

---

## 9. Revision log

| Version | Date | Note |
|---------|------|------|
| 0.1.0 | 2026-07-23 | Thin local loader (approach B) |
| 0.2.0 | 2026-07-23 | **Approach A:** coding-agent package-manager **local isomorphic subset**; ADR 0006; omit install/npm/git/home |
| 0.2.1 | 2026-07-23 | Implemented: package_manager local subset + echo_example + C0/C1 |
