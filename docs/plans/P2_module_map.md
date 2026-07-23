# P2 Module Map

| upstream path | python path | status | notes |
|---------------|-------------|--------|-------|
| `src/types.ts` | `packages/agent/src/earendil_works/pi_agent/types.py` | done | StreamFn, AgentTool, AgentEvent, … |
| `src/agent-loop.ts` | `packages/agent/src/earendil_works/pi_agent/agent_loop.py` | done | agent_loop / continue + tools |
| `src/agent.ts` | `packages/agent/src/earendil_works/pi_agent/agent.py` | done | continue_ host-delta name |
| `src/stream-fn.ts` | `packages/agent/src/earendil_works/pi_agent/stream_fn.py` | done | |
| `src/proxy.ts` | `packages/agent/src/earendil_works/pi_agent/proxy.py` | todo | |
| `src/index.ts` | `packages/agent/src/earendil_works/pi_agent/__init__.py` | todo | partial re-exports (types + stream_fn) |
| `src/node.ts` | `packages/agent/src/earendil_works/pi_agent/node.py` | host-delta | Node-only exports |
| `src/harness/agent-harness.ts` | `…/harness/agent_harness.py` | todo | |
| `src/harness/types.ts` | `…/harness/types.py` | todo | |
| `src/harness/messages.ts` | `…/harness/messages.py` | todo | |
| `src/harness/skills.ts` | `…/harness/skills.py` | todo | |
| `src/harness/system-prompt.ts` | `…/harness/system_prompt.py` | todo | |
| `src/harness/prompt-templates.ts` | `…/harness/prompt_templates.py` | todo | |
| `src/harness/session/session.ts` | `…/harness/session/session.py` | todo | DEFAULT_SESSIONS_DIR_NAME scaffold |
| `src/harness/session/jsonl-storage.ts` | `…/harness/session/jsonl_storage.py` | todo | JSONL SoT |
| `src/harness/session/jsonl-repo.ts` | `…/harness/session/jsonl_repo.py` | todo | |
| `src/harness/session/memory-storage.ts` | `…/harness/session/memory_storage.py` | todo | |
| `src/harness/session/memory-repo.ts` | `…/harness/session/memory_repo.py` | todo | |
| `src/harness/session/repo-utils.ts` | `…/harness/session/repo_utils.py` | todo | |
| `src/harness/compaction/compaction.ts` | `…/harness/compaction/compaction.py` | todo | |
| `src/harness/compaction/branch-summarization.ts` | `…/harness/compaction/branch_summarization.py` | todo | |
| `src/harness/compaction/utils.ts` | `…/harness/compaction/utils.py` | todo | |
| `src/harness/tools/index.ts` | `…/harness/tools/__init__.py` | todo | |
| `src/harness/tools/read.ts` | `…/harness/tools/read.py` | todo | |
| `src/harness/tools/write.ts` | `…/harness/tools/write.py` | todo | |
| `src/harness/tools/edit.ts` | `…/harness/tools/edit.py` | todo | |
| `src/harness/tools/edit-diff.ts` | `…/harness/tools/edit_diff.py` | todo | pathspec/difflib host-delta |
| `src/harness/tools/bash.ts` | `…/harness/tools/bash.py` | todo | |
| `src/harness/tools/image.ts` | `…/harness/tools/image.py` | todo | |
| `src/harness/tools/path-utils.ts` | `…/harness/tools/path_utils.py` | todo | |
| `src/harness/tools/file-mutation-queue.ts` | `…/harness/tools/file_mutation_queue.py` | todo | |
| `src/harness/tools/tool-context.ts` | `…/harness/tools/tool_context.py` | todo | |
| `src/harness/utils/truncate.ts` | `…/harness/utils/truncate.py` | todo | |
| `src/harness/utils/shell-output.ts` | `…/harness/utils/shell_output.py` | todo | |
| `src/harness/env/nodejs.ts` | `…/harness/env/python_env.py` | host-delta | Node → Python stdlib |
| SQLite session (`pi-storage-sqlite-node`) | — | host-delta | **not required for P2 exit** if JSONL complete |
| `ignore` / `diff` npm | pathspec / difflib | host-delta | Python equivalents |

Paths abbreviated with `…` = `packages/agent/src/earendil_works/pi_agent`.

Upstream SHA: see `docs/plans/UPSTREAM_SHA.txt`  
Snapshot: `c55ae2faa5d850e0e4650bd573f7f241b10e2e0b`  
npm: `@earendil-works/pi-agent-core@0.81.1`

Status: `todo` | `done` | `host-delta`
