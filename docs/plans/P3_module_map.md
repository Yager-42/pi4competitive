# P3 Module Map — coding-agent package **local isomorphic subset**

Upstream pin: see `docs/plans/UPSTREAM_SHA.txt`  
Contract: **v0.3.2** · ADR **0006**  
Plan: `docs/plans/P3_capability_loader.md` v0.2.0

Status: `todo` | `done` | `host-delta` | `omit`

## Port / host-delta

| upstream path | python path | status | notes |
|---------------|-------------|--------|-------|
| `coding-agent/src/core/package-manager.ts` (types + local collect + resolve local) | `pi_agent/package_manager/types.py` + `collect.py` + `package_manager.py` | todo | **omit** install/npm/git/update/remove |
| `coding-agent/src/core/resource-loader.ts` (load from resolved paths) | `pi_agent/package_manager/resource_loader.py` | todo | omit themes/TUI; omit ~/.pi defaults |
| `coding-agent/src/core/extensions/loader.ts` | `pi_agent/package_manager/extensions_loader.py` | host-delta | TS/jiti → Python register/tools |
| `coding-agent/src/core/skills.ts` | reuse `harness/skills.py` + package discovery | todo | |
| `coding-agent` prompt template load | reuse `harness/prompt_templates.py` | todo | |
| `coding-agent/docs/packages.md` (structure/filter local) | `capability_packages/README.md` | todo | install chapters not applicable |

## Explicit omit (must stay omit)

| upstream | status |
|----------|--------|
| `PackageManager.install*` / `remove*` / `update` / `checkForAvailableUpdates` | omit |
| npm / git source install & clone | omit |
| `package-manager-cli.ts` | omit |
| `getExtensionTempFolder` temporary installs | omit |
| user home / `~/.pi` package roots | omit |
| themes resource type (optional later) | omit |

## Example package

| path | status |
|------|--------|
| `capability_packages/echo_example` | todo |

## Public API

| symbol | status |
|--------|--------|
| `load_capability_packages` | todo |
| `LocalPackageManager.resolve` | todo |
| `apply_capability_report` / apply tools to Agent | todo |
