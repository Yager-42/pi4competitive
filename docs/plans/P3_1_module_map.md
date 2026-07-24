# P3.1 Module Map — coding-agent **extension runtime** (S-engine)

Upstream pin: see `docs/plans/UPSTREAM_SHA.txt`  
Local mirror: `vendor/earendil-works-pi/packages/coding-agent/src/core/extensions/`  
Contract: **v0.3.4** · ADR **0008** (+ ADR **0006** omit install)  
Feature: `docs/features/agent_engine_extensions_v1.md` **v0.2.2 frozen**  
Plan: `docs/plans/P3_1_agent_engine_extensions.md` **v0.2.3 completed**

Status: `todo` | `done` | `host-delta` | `omit`

## Port / host-delta

| upstream path | python path | status | notes |
|---------------|-------------|--------|-------|
| `coding-agent/src/core/extensions/types.ts` | `pi_agent/extensions/types.py` | done | IN events + C-engine Context only; OUT not public |
| `coding-agent/src/core/extensions/loader.ts` | `pi_agent/extensions/loader.py` | host-delta | `create_extension_runtime` / `load_extensions`; `.py`+importlib |
| `coding-agent/src/core/extensions/runner.ts` | `pi_agent/extensions/runner.py` | done | `ExtensionRunner` dispatch + merge; no UI/command tree |
| `coding-agent/src/core/extensions/wrapper.ts` | `pi_agent/extensions/wrapper.py` | done | `wrap_registered_tools` |
| `coding-agent/src/core/extensions/index.ts` | `pi_agent/extensions/__init__.py` | done | AP3 public exports |
| `coding-agent/src/core/agent-session.ts` (runner bind/emit) | `pi_agent/agent.py` + `agent_loop.py` + harness | host-delta | §3.1 IN emitted by engine host |
| package-manager local load of extensions | `package_manager/*` evolve → call `extensions.loader` | host-delta | E2 Python local loader; install still omit |
| P3 `CapabilityRegisterApi` / `apply_capability_report` | converge under AP3 attach | done | obsolete API removed; apply is thin attach wrapper |

## Explicit omit (must stay omit)

| upstream | status |
|----------|--------|
| `ExtensionUIContext` / `ui` / `hasUI` / theme / widgets | omit |
| events: `project_trust`, `input`, `user_bash` | omit |
| events: `session_before_switch`, `session_before_fork`, `session_before_tree`, `session_tree` | omit |
| event: `resources_discover` | omit |
| `ExtensionCommandContext` fork/switch/navigateTree/newSession/reload | omit |
| TUI `registerCommand` / `registerShortcut` / `registerFlag` / message·entry renderers | omit (default) |
| `discoverAndLoadExtensions` home / `~/.pi` / agentDir auto | omit |
| `PackageManager.install*` / npm / git / `pi install` | omit (ADR 0006) |

## Public API (AP3)

| symbol | status |
|--------|--------|
| `create_extension_runtime` | done |
| `load_extensions` | done |
| `load_extension_from_factory` | done |
| `ExtensionRunner` | done |
| `wrap_registered_tools` / `wrap_registered_tool` | done |
| `ExtensionAPI.on` (IN only) | done |
| `ExtensionAPI.register_tool` / `registerTool` | done |
| Attach path (runner → Agent + tools) | done |

## Consumers (M2 / SK2)

| path | status | notes |
|------|--------|-------|
| `capability_packages/echo_example` | done | glue → `registerTool` |
| `capability_packages/search_tavily` | done | glue only |
| `capability_packages/search_anysearch` | done | glue only |
| `capability_packages/search_grok` | done | glue only |
| skills/prompts apply to harness (SK2) | done | no parallel `add_skill` brand |

## Docs closeout

| item | status |
|------|--------|
| search feature doc `add_tool` wording | done |
| roadmap P3.1=done | done |
| plan status completed | done |
