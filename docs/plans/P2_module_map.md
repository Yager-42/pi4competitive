# P2 Module Map

| upstream path | python path | status | notes |
|---------------|-------------|--------|-------|
| `src/types.ts` | `packages/agent/src/earendil_works/pi_agent/types.py` | done | StreamFn, AgentTool, AgentEvent, … |
| `src/agent-loop.ts` | `packages/agent/src/earendil_works/pi_agent/agent_loop.py` | done | agent_loop / continue + tools |
| `src/agent.ts` | `packages/agent/src/earendil_works/pi_agent/agent.py` | done | continue_ host-delta name |
| `src/stream-fn.ts` | `packages/agent/src/earendil_works/pi_agent/stream_fn.py` | done | |
| `src/proxy.ts` | `packages/agent/src/earendil_works/pi_agent/proxy.py` | host-delta | stub reserved; unused for P2 exit |
| `src/index.ts` | `packages/agent/src/earendil_works/pi_agent/__init__.py` | done | public re-exports |
| `src/node.ts` | `packages/agent/src/earendil_works/pi_agent/node.py` | host-delta | Node-only exports |
| `src/harness/agent-harness.ts` | `…/harness/agent_harness.py` | done | thin façade + session persist |
| `src/harness/types.ts` | `…/harness/types.py` | done | session + Result/errors (subset) |
| `src/harness/messages.ts` | `…/harness/messages.py` | done | |
| `src/harness/skills.ts` | `…/harness/skills.py` | done | path-based load (no home scan) |
| `src/harness/system-prompt.ts` | `…/harness/system_prompt.py` | done | |
| `src/harness/prompt-templates.ts` | `…/harness/prompt_templates.py` | done | |
| `src/harness/session/session.ts` | `…/harness/session/session.py` | done | DEFAULT_SESSIONS_DIR_NAME |
| `src/harness/session/jsonl-storage.ts` | `…/harness/session/jsonl_storage.py` | done | JSONL SoT |
| `src/harness/session/jsonl-repo.ts` | `…/harness/session/jsonl_repo.py` | done | |
| `src/harness/session/memory-storage.ts` | `…/harness/session/memory_storage.py` | done | |
| `src/harness/session/memory-repo.ts` | `…/harness/session/memory_repo.py` | done | |
| `src/harness/session/repo-utils.ts` | `…/harness/session/repo_utils.py` | done | |
| `src/harness/compaction/compaction.ts` | `…/harness/compaction/compaction.py` | done | thresholds + fallback summary |
| `src/harness/compaction/branch-summarization.ts` | `…/harness/compaction/branch_summarization.py` | done | |
| `src/harness/compaction/utils.ts` | `…/harness/compaction/utils.py` | host-delta | unused; logic inlined in compaction |
| `src/harness/tools/index.ts` | `…/harness/tools/__init__.py` | done | coding tools subset |
| `src/harness/tools/read.ts` | `…/harness/tools/read.py` | done | |
| `src/harness/tools/write.ts` | `…/harness/tools/write.py` | done | |
| `src/harness/tools/edit.ts` | `…/harness/tools/edit.py` | host-delta | stub; not required for exit smoke |
| `src/harness/tools/edit-diff.ts` | `…/harness/tools/edit_diff.py` | host-delta | stub |
| `src/harness/tools/bash.ts` | `…/harness/tools/bash.py` | host-delta | stub |
| `src/harness/tools/image.ts` | `…/harness/tools/image.py` | host-delta | stub |
| `src/harness/tools/path-utils.ts` | `…/harness/tools/path_utils.py` | host-delta | stub |
| `src/harness/tools/file-mutation-queue.ts` | `…/harness/tools/file_mutation_queue.py` | host-delta | stub |
| `src/harness/tools/tool-context.ts` | `…/harness/tools/tool_context.py` | host-delta | stub |
| `src/harness/utils/truncate.ts` | `…/harness/utils/truncate.py` | host-delta | stub |
| `src/harness/utils/shell-output.ts` | `…/harness/utils/shell_output.py` | host-delta | stub |
| `src/harness/env/nodejs.ts` | `…/harness/env/python_env.py` | host-delta | LocalFileSystem Result API |
| SQLite session (`pi-storage-sqlite-node`) | — | host-delta | **not required for P2 exit** if JSONL complete |
| `ignore` / `diff` npm | pathspec / difflib | host-delta | deferred with edit tool |

Paths abbreviated with `…` = `packages/agent/src/earendil_works/pi_agent`.

Upstream SHA: see `docs/plans/UPSTREAM_SHA.txt`  
Snapshot: `c55ae2faa5d850e0e4650bd573f7f241b10e2e0b`  
npm: `@earendil-works/pi-agent-core@0.81.1`

Status: `todo` | `done` | `host-delta`
