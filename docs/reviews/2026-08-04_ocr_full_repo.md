# Review 快照：OCR 全仓审查 2026-08-04

## 1. 运行信息

| 项 | 值 |
|---|---|
| 命令 | `ocr review --from 8443266 --to HEAD --audience agent --format json`（4 轮 resume + 1 轮补审） |
| 范围 | 根提交 `8443266`（docs-only）之后全部变更 = 整个代码库 |
| 排除 | `**/*.md, **/tests/**, **/test_*.py, **/conftest.py, **/fixtures/**, **/docs/**` |
| 文件 | 443/443 selected 全部完成（policy.py 补审 `--timeout 30`） |
| Finding | 417（critical 2 / high 86 / medium 220 / low 79 / none 30） |
| 成本 | 约 46M tokens，4 轮预算（5M/20M/30M/50M）+ 补审 |
| 原始数据 | [`ocr-2026-08-04-raw.json`](ocr-2026-08-04-raw.json)（623KB，417 条 content + suggestion_code + existing_code；**无 thinking 字段**） |

## 2. 结论速览

- **226 条 bug/security** 进 [`docs/known-issues.md`](../known-issues.md)（P1 High/Critical 67 + P2 Medium/未标级 159；修一条删一条）。
- **10 条有意 host-delta**、**9 条移植欠账（owner 2026-08-04 拍板范围外）**→ 移出清单，见 §4.5。
- 1 条误报（seccomp vendor 路径，§4）；1 条故意 stub（edit.py，§4）。

## 3. High / Critical 全量（88）

### packages/ai

**packages/ai/src/earendil_works/pi_ai/api/anthropic_messages.py:38-45** [bug] `run()` is scheduled as a background task, but payload construction and `onPayload` execution occur before the `try` that emits an error and closes `outer`. If the transformer or callback raises (for example, malformed context or a user callback rejecting the payload), the task terminates with an un
**packages/ai/src/earendil_works/pi_ai/api/azure_openai_responses.py:8-9** [bug 🎯有意 host-delta（§4.5）] This makes the Azure provider use the generic OpenAI-compatible Chat Completions transport unchanged. That transport derives `<model.baseUrl>/chat/completions` (and defaults to `https://api.openai.com/v1`) and sends `Authorization: Bearer ...`, whereas Azure OpenAI requires the deployment-scoped end
**packages/ai/src/earendil_works/pi_ai/api/bedrock_converse_stream.py:9-9** [bug 🎯有意 host-delta（§4.5）] This routes every Amazon Bedrock model through the OpenAI Chat Completions transport. That transport requires `options.apiKey`, sends a Bearer-authenticated `/chat/completions` request, and builds an OpenAI payload, whereas Bedrock Converse requires AWS SigV4 authentication and the `ConverseStream` 
  - 建议：return _bedrock_converse_stream(model, context, options)
**packages/ai/src/earendil_works/pi_ai/api/google_generative_ai.py:10-10** [bug 🎯有意 host-delta（§4.5）] This makes the Google provider call the OpenAI Chat Completions protocol (`<baseUrl>/chat/completions` with a Bearer key and OpenAI-shaped payload), but `google_provider()` supplies the Gemini base URL (`generativelanguage.googleapis.com/v1beta`). Gemini requires its `generateContent`/`streamGenerat
**packages/ai/src/earendil_works/pi_ai/api/google_shared.py:27-35** [bug] Tool-result messages are classified as `user`, but their content is never read: `text` is populated only for `user` and `assistant`, so every tool response is sent to Google as an empty part. This drops tool output and can make subsequent tool calls fail or hallucinate; handle `toolResult` content (
**packages/ai/src/earendil_works/pi_ai/api/google_shared.py:32-36** [bug] Assistant `toolCall` blocks are ignored by this conversion, so the model's function-call turn is reduced to an empty text part (or only its textual content). Google APIs require a `functionCall` part, including the function name and arguments, for the following function response to be valid; preserv
**packages/ai/src/earendil_works/pi_ai/api/google_vertex.py:8-9** [bug 🎯有意 host-delta（§4.5）] This routes every Vertex request through the OpenAI chat-completions implementation. That implementation appends `/chat/completions`, sends an `Authorization: Bearer` API key, and builds an OpenAI payload, whereas Vertex Gemini uses the `.../v1/projects/{project}/locations/{location}/publishers/goog
**packages/ai/src/earendil_works/pi_ai/api/mistral_conversations.py:9-9** [bug 🎯有意 host-delta（§4.5）] This routes every `mistral-conversations` model through the OpenAI chat-completions transport. With the configured Mistral `baseUrl` (`https://api.mistral.ai`), that transport constructs `https://api.mistral.ai/chat/completions` (it only appends `/chat/completions`), whereas Mistral's endpoints are 
**packages/ai/src/earendil_works/pi_ai/api/openai_codex_responses.py:6-9** [bug 🎯有意 host-delta（§4.5）] This adapter reuses `openai_responses.stream`, which in this codebase immediately delegates to the OpenAI Chat Completions transport. For every Codex model here, `baseUrl` is `https://chatgpt.com/backend-api`, so the request is sent to `/backend-api/chat/completions`; the Codex provider requires its
**packages/ai/src/earendil_works/pi_ai/api/openai_completions.py:44-51** [bug] Exceptions raised while creating the inner stream or while forwarding its events escape this background task before `outer.end()` is called. The task then finishes with an unobserved exception while consumers waiting on the outer stream block forever. Wrap the whole `run()` body in `try/except Excep
**packages/ai/src/earendil_works/pi_ai/api/openai_completions.py:53-57** [bug] When `stream()` is invoked without an already-running event loop, `get_running_loop()` raises and this `pass` leaves `outer` permanently unfinished: no provider request is started and no terminal event/result is emitted. This API returns a stream synchronously, and callers can invoke provider stream
**packages/ai/src/earendil_works/pi_ai/api/openai_responses.py:22-22** [bug 🎯有意 host-delta（§4.5）] This implementation is registered as `openai-responses` (including the OpenAI provider), but it sends the request through the Chat Completions transport. That transport always posts to `/chat/completions` and parses `choices[].delta` events, whereas the Responses API requires `/responses` and emits 
**packages/ai/src/earendil_works/pi_ai/api/openrouter_images.py:7-17** [bug] `generate_images` never calls OpenRouter (or any provider) and always returns `stopReason: "error"` with an empty output. Since this function is the registered implementation used by `images.generate` for every `openrouter-images` model, image generation is unconditionally nonfunctional even when va
  - 建议：async def generate_images(model: Model, context: ImagesContext, options: dict[str, Any] | None = None) -> AssistantImages:     # Call the configured OpenRouter 
**packages/ai/src/earendil_works/pi_ai/auth/credential_store.py:30-32** [bug] This treats a mutator result of `None` as deletion, but callers use `None` as a no-write signal (for example, the OAuth refresh path returns `None` when another task has already refreshed the credential). In that race this deletes the still-valid credential, causing subsequent authentication failure
**packages/ai/src/earendil_works/pi_ai/providers/anthropic.py:14-14** [security] `ANTHROPIC_OAUTH_TOKEN` is resolved through the API-key auth path, and `anthropic_messages.stream` always sends the resolved value as `x-api-key`. Anthropic OAuth tokens are bearer credentials and cannot be used as API keys, so configuring this environment variable makes every request fail (and risk
  - 建议："auth": {"apiKey": env_api_key_auth("Anthropic API key", ["ANTHROPIC_API_KEY"])},
**packages/ai/src/earendil_works/pi_ai/providers/azure_openai_responses.py:10-16** [bug] This provider never supplies an Azure endpoint (or deployment/API version), and every catalog model has an empty `baseUrl`. The delegated HTTP implementation therefore falls back to `https://api.openai.com/v1/chat/completions`, so selecting this provider sends the Azure API key to the public OpenAI 
**packages/ai/src/earendil_works/pi_ai/providers/cloudflare_ai_gateway.py:4-5** [bug] This auth resolver always returns an empty `auth` object, so `_apply_auth` never places an API key into the request options. All three HTTP implementations then fail their required `apiKey` check (and no Authorization header is sent), making every Cloudflare AI Gateway model request fail unless call
**packages/ai/src/earendil_works/pi_ai/providers/cloudflare_workers_ai.py:16-18** [bug] Every catalog model has a `baseUrl` containing the literal `{CLOUDFLARE_ACCOUNT_ID}` placeholder, but this provider supplies no base URL or resolution step that expands it. The HTTP client uses `model["baseUrl"]` verbatim, so requests are sent to an invalid URL unless callers rewrite every model the
**packages/ai/src/earendil_works/pi_ai/providers/cloudflare_workers_ai.py:4-5** [bug] This resolver always returns an empty `auth` object, so `_apply_auth` cannot populate `options["apiKey"]`; the shared OpenAI-completions transport then rejects every request as `Missing API key` (and `getAvailable` incorrectly treats the provider as configured because the resolver returned a non-`No
**packages/ai/src/earendil_works/pi_ai/providers/faux.py:490-492** [bug] When `stream()` is called without a running event loop, this assigns the coroutine to a private attribute that `AssistantMessageEventStream` never consumes (its iterator only waits for pushed events). No later code in this provider schedules `_pending_run`, so the returned stream never emits or comp
**packages/ai/src/earendil_works/pi_ai/providers/github_copilot.py:20-21** [bug] The catalog includes multiple `anthropic-messages` GitHub Copilot models, but this adapter always authenticates with the Anthropic `x-api-key` header. GitHub Copilot's proxy expects the Copilot token in `Authorization: Bearer ...` (as used by its OpenAI-compatible endpoints), so these models will fa
**packages/ai/src/earendil_works/pi_ai/providers/google.py:16-16** [bug 🎯有意 host-delta（§4.5）] The Google provider is wired to `google_generative_ai_api()`, but that API currently delegates to the OpenAI Chat Completions transport. Consequently calls use `<baseUrl>/chat/completions` with a Bearer token, while Gemini's Generative Language API requires the `models/{model}:generateContent`/`stre
  - 建议："api": google_generative_ai_api(),  # use a transport that targets Gemini's native endpoint
**packages/ai/src/earendil_works/pi_ai/providers/google_vertex.py:16-16** [bug] The provider resolves ambient credentials to an empty auth object, so `_apply_auth` passes no `apiKey` to the selected stream implementation. Normal Vertex calls therefore reach the HTTP layer without credentials and fail as `Missing API key`; this provider needs to resolve ADC/service-account crede
**packages/ai/src/earendil_works/pi_ai/providers/openai.py:16-16** [bug 🎯有意 host-delta（§4.5）] All models returned by `get_models()` are catalogued with `api: "openai-responses"`, so this provider routes every OpenAI request through `open_ai_responses_api()`. That implementation currently delegates to the Chat Completions streamer, which sends a `/chat/completions` payload rather than the Res
  - 建议："api": native_openai_responses_api(),
**packages/ai/src/earendil_works/pi_ai/providers/radius.py:16-17** [bug] This provider is registered as a built-in provider, but it exposes no models and does not provide `fetchModels`; consequently `getModels("radius")`, `getAvailable()`, and normal model lookup can never return a Radius model, so the provider cannot be used through the standard model-management API. Po
**packages/ai/src/earendil_works/pi_ai/providers/xai.py:19-19** [bug 🎯有意 host-delta（§4.5）] The `grok-4.5` model in `xai_models` is declared with `api: "openai-responses"`, so `create_provider` dispatches it to this entry. However, `open_ai_responses_api()` currently delegates to the Chat Completions streamer and posts to `/chat/completions`, not the Responses API endpoint/payload. As a re

### packages/agent

**packages/agent/src/earendil_works/pi_agent/agent.py:554-557** [bug] Cleanup is not protected from failures in the settled-event dispatch. `ExtensionRunner.emit()` can still raise before it reaches its per-handler `try` block (for example, if the runner has been invalidated by `shutdown_extensions()` while this run is finishing), so `_finish_run()` is skipped. The ac
  - 建议：finally:             try:                 if self.extension_runner:                     await self.extension_runner.emit({"type": "agent_settled"})             
**packages/agent/src/earendil_works/pi_agent/agent_loop.py:86-88** [bug] If `_run` raises before reaching `stream.end` (for example, stream resolution, `response.result()`, or a lifecycle callback raises), the background task exits without marking this `EventStream` complete. `await_result()` then waits forever because `EventStream` has no failure/exception completion pa
**packages/agent/src/earendil_works/pi_agent/extensions/wrapper.py:50-58** [bug] For a normal extension loaded from under `runner.cwd`, this constructs the target with the cwd directory name as an extra package prefix (for example, `repo_name.capability_packages.echo_example.extensions.echo_tools`). The worker imports this string as a Python module, while the materialized extens
**packages/agent/src/earendil_works/pi_agent/harness/agent_harness.py:169-173** [bug] The native compaction paths only compute and return the helper result; unlike the extension-plan path, they neither append a compaction entry to the session nor rebuild `agent.state.messages` from the compacted context. `prompt()` reloads the session on every invocation, so this compaction is lost i
**packages/agent/src/earendil_works/pi_agent/harness/compaction/compaction.py:128-131** [bug] `stream_fn` and `model` are accepted by this API and passed by `AgentHarness.compact`, but they are never used here. For any history longer than 500 characters, compaction therefore keeps only a fixed prefix and discards the remainder instead of producing an LLM summary, losing prior instructions, d
**packages/agent/src/earendil_works/pi_agent/harness/session/session.py:53-60** [bug] When `firstKeptEntryId` is present but does not occur before this compaction on the selected path, `found` remains false and no historical entries are appended. The resulting context silently discards the entire pre-compaction history, even though the storage traversal can still return it when the m
**packages/agent/src/earendil_works/pi_agent/harness/tools/edit.py:7-7** [bug 📌有记录（故意）] This module does not implement or export any edit tool: `__all__` is empty and there is no `create_edit_tool`/executor. As a result, importing this module cannot provide the advertised file-edit capability, and the agent has no edit operation (only read/write are registered elsewhere). Implement the
  - 建议：__all__ = ["create_edit_tool"]
**packages/agent/src/earendil_works/pi_agent/package_manager/apply.py:71-72** [bug] The merged tool list is discarded here. `merge_tools` computes the result for both collision policies, but `agent.state.tools` is never assigned, so capability tools in `report.tools` (and any replacement selected by `policy="replace"`) are not applied. Assign the merged list to `agent.state.tools` 
  - 建议：merged, diags = merge_tools(list(agent.state.tools), list(report.tools), policy=policy)     agent.state.tools = merged     report.extension_runner = attach_exte
**packages/agent/src/earendil_works/pi_agent/package_manager/collect.py:119-124** [security] `is_file()`/`is_dir()` follow symlinks here, and the collected paths are then resolved, but no check ensures the resolved target is beneath `dir_path`. A symlinked `SKILL.md` or extension can therefore make resource discovery escape the package root; reject such symlinks or enforce resolved-target c
**packages/agent/src/earendil_works/pi_agent/package_manager/collect.py:183-186** [security] Nested extension directories are inspected through symlink-following `is_dir()` and their entries are resolved without checking containment under the package root. A symlinked directory can therefore inject extension files from outside the package. Ensure the directory and every returned file resolv
**packages/agent/src/earendil_works/pi_agent/package_manager/collect.py:347-349** [security] The manifest entry is resolved after joining to `root`, but no containment check is performed. An entry such as `../outside.py` (or a directory traversal equivalent) can cause collection of resources outside the package root and can feed an unintended extension into the loader. Validate the resolved
**packages/agent/src/earendil_works/pi_agent/package_manager/collect.py:351-352** [security] The manifest glob branch has the same package-boundary escape as the literal branch: `root.glob('../*.py')` can return matches outside `root`, which are then resolved and collected. Reject glob patterns that resolve outside the package root (and validate each match's resolved containment) before pas
**packages/agent/src/earendil_works/pi_agent/package_manager/collect.py:80-83** [security] These checks follow symlinks and append the resolved target without verifying it remains under `dir_path`. A package can therefore expose files outside its resource root; for extensions the returned path is later imported/executed, so a symlink in a package can bypass the package boundary. Reject sy
**packages/agent/src/earendil_works/pi_agent/package_manager/package_manager.py:71-79** [security] `child.is_dir()` follows symlinks, and `child.resolve()` can therefore produce a package directory outside `self.root`. The subsequent collection and extension loader will trust and execute resources from that escaped directory, so a symlink under `capability_packages` bypasses the configured local-
  - 建议：if not child.is_dir():                 continue             resolved = child.resolve()             try:                 resolved.relative_to(self.root)         
**packages/agent/src/earendil_works/pi_agent/tool_execution.py:90-98** [security] This derives a target solely from `__module__`/`__qualname__` metadata and never verifies that importing that module and resolving that name yields the same function. As a result, dynamically loaded functions, deleted/renamed module attributes, or monkey-patched names are advertised as valid remote 
  - 建议：module = getattr(original, "__module__", None)     qualname = getattr(original, "__qualname__", None)     if not isinstance(module, str) or not module:         

### competitive_app sandbox（native/srt/vendor）

**competitive_app/src/competitive_app/adapter/out/sandbox/approved_registry.py:148-150** [security] `build_identity` is accepted from the manifest and then ignored during validation. `verify_startup` passes the host-generated identity into its `build_identity` parameter, but this method has no expected-identity argument and never compares it with `manifest.build_identity`; consequently a manifest 
  - 建议：def validate_baked_manifest(self, manifest: ApprovedToolManifest, *, expected_build_identity: str) -> None:         if manifest.protocol != PROTOCOL_NAME or man
**competitive_app/src/competitive_app/adapter/out/sandbox/native/broker.py:201-202** [security] The broker launches the target with the entire broker environment. In the normal `NativeRuntime` path, `self._env` defaults to an empty dict, but `spawn_broker` uses `options.env or os.environ`, so that empty environment is replaced with the host environment; the broker then passes it unchanged to u
  - 建议：env=_target_environment(),         stdin=asyncio.subprocess.PIPE,
**competitive_app/src/competitive_app/adapter/out/sandbox/native/native_sandbox_provider.py:160-164** [bug] `release()` closes only the runtime's admission flag; `NativeRuntime.close()` does not track or terminate an in-flight `run_sandboxed_command`. Because the scope signal is completed only after `_close_sandbox()` returns, an active worker is neither aborted nor awaited here, so release can return whi
**competitive_app/src/competitive_app/adapter/out/sandbox/native/network_policy.py:140-145** [security] This validates DNS only for the approval request and then forwards the hostname. The SRT proxy subsequently resolves that hostname again when it dials the destination, so a DNS rebinding/change between these two lookups can make the approved hostname resolve to a private/loopback/link-local address 
**competitive_app/src/competitive_app/adapter/out/sandbox/native/policy.py:213-216** [security] On Linux, `denyWrite` entries are converted to `denyWithinAllow` and the SRT Linux backend explicitly drops glob patterns, so only these fixed root-level names/directories protect first-time creations. The extension and `.env.*` rules are only materialized for files found by the scan; a sandboxed pr
**competitive_app/src/competitive_app/adapter/out/sandbox/native/srt/linux.py:410-416** [security] The socat UNIX listeners are created without a restrictive socket mode. `UNIX-LISTEN` normally creates the socket with permissions derived from its default mode and the process umask (often allowing other local users to connect), while this path is subsequently exposed to the sandbox and may carry a
  - 建议：return [         f"UNIX-LISTEN:{listen_path},fork,reuseaddr,mode=0600",         (             f"TCP:localhost:{target_port},keepalive,keepidle=10,"             
**competitive_app/src/competitive_app/adapter/out/sandbox/native/srt/linux.py:951-956** [security] When a denyWrite destination is exactly the same path as a denyRead tmpfs directory (for example, `allowOnly: [dir]` together with `denyOnly: [dir]`), `is_hidden_by_tmpfs` allows the bind because the write path re-exposes that directory. However, this re-application condition only matches tmpfs dire
  - 建议：for tmpfs_dir in tmpfs_dirs:         if any(             tmpfs_dir == dest or tmpfs_dir.startswith(dest + "/")             for dest in emitted_deny_write_dests 
**competitive_app/src/competitive_app/adapter/out/sandbox/native/srt/manager.py:321-326** [bug] When dependency checks fail, `_config` is cleared and the exception is raised before `_initialization_error` is recorded or `_initialization_done` is set. A concurrent `wrap_with_sandbox()` can already have observed the temporary config and be waiting in `wait_for_network_initialization()`; that eve
**competitive_app/src/competitive_app/adapter/out/sandbox/native/srt/manager.py:635-641** [security] Network enforcement is enabled only when `allowedDomains` is present. Valid configurations containing only `deniedDomains` (including `{"deniedDomains": ["*"]}`) or `strictAllowlist` therefore pass `needs_network_restriction=False` and launch without the proxy/network sandbox, allowing the command t
**competitive_app/src/competitive_app/adapter/out/sandbox/native/srt/manager.py:835-837** [bug] `reset()` clears `_initialization_done` but leaves `_initialization_lock` intact. The next `initialize()` skips lock creation and immediately calls `_initialization_done.is_set()` on `None`, raising `AttributeError` instead of allowing the sandbox session to be reinitialized. Reset the lock as well,
**competitive_app/src/competitive_app/adapter/out/sandbox/native/srt/proxy.py:593-595** [security] The HTTP CONNECT path sends the raw parsed hostname to both the allowlist and `dial_direct` without applying the validation/canonicalization used by the SOCKS path. In particular, bracketed IPv6 targets can contain zone identifiers (for example `%25eth0`), and alternate IP spellings can be interpret
**competitive_app/src/competitive_app/adapter/out/sandbox/native/srt/proxy.py:763-764** [bug] `_read_headers` preserves the header-name casing, but this lookup only recognizes an exactly lowercase `transfer-encoding`. A normal `Transfer-Encoding: chunked` request therefore falls through to the content-length path, returns an empty body, and leaves the chunk bytes in the stream to be parsed a
**competitive_app/src/competitive_app/adapter/out/sandbox/native/srt/proxy.py:765-766** [security] Request bodies are accumulated/read with no maximum size. A client can send an arbitrarily large chunked body (or advertise a very large `Content-Length`), forcing the proxy to retain it in memory before forwarding and potentially exhausting the process. Enforce a configured request-body limit while
**competitive_app/src/competitive_app/adapter/out/sandbox/native/srt/proxy.py:784-785** [bug] This response lookup has the same case-sensitivity defect: `_read_headers` retains names such as `Content-Length` and `Transfer-Encoding`, so standard-cased responses are treated as close-delimited. Since `strip_hop_by_hop` removes `Transfer-Encoding`, the proxy can forward a chunked body without it
**competitive_app/src/competitive_app/adapter/out/sandbox/native/srt/seccomp.py:100-103** [security ⚠️误报] The default resolution points at `native/vendor/seccomp/<arch>/apply-seccomp`, but this change set only adds `native/vendor/seccomp-src/apply-seccomp.c`; no `x64`/`arm64` helper binaries or build/package step creates them. Consequently, on a normal Linux installation the lookup returns `None`, and `
  - 注：vendor 二进制是发布物（G0 §5.1 pin），seccomp-src 仅 provenance；缺失时 fail-closed
**competitive_app/src/competitive_app/adapter/out/sandbox/native/vendor/seccomp-src/apply-seccomp.c:332-334** [bug] This probe only establishes support for `SECCOMP_FILTER_FLAG_TSYNC_ESRCH`; that flag's availability is not a valid indication that `SECCOMP_USER_NOTIF_FLAG_CONTINUE` is accepted. On a kernel that supports the listener but rejects `CONTINUE`, `SECCOMP_IOCTL_NOTIF_SEND` can fail with `EINVAL` while th
**competitive_app/src/competitive_app/adapter/out/sandbox/native/vendor/seccomp-src/apply-seccomp.c:500-500** [bug] If any allocation fails after the listener has been installed, this early return leaves `notify_fd` unmanaged while the worker remains alive. The next matched syscall receives `SECCOMP_RET_USER_NOTIF` and blocks waiting for a response, while the outer stub then waits for that child, so an allocation
**competitive_app/src/competitive_app/adapter/out/sandbox/native/vendor/seccomp-src/seccomp-unix-block.c:99-100** [security] This filter blocks only `socket(AF_UNIX, ...)`; on supported 64-bit architectures, `socketpair(AF_UNIX, ...)` is a separate syscall and can still create Unix-domain endpoints without matching this rule. That bypasses the stated Unix-socket isolation boundary. Add a corresponding `SCMP_SYS(socketpair
  - 建议：rc = seccomp_rule_add(ctx, SCMP_ACT_ERRNO(EPERM), SCMP_SYS(socket), 1,                           SCMP_A0(SCMP_CMP_MASKED_EQ, 0xffffffff, AF_UNIX));     if (rc =
**competitive_app/src/competitive_app/adapter/out/sandbox/native/workspace.py:75-77** [security] The containment/symlink checks are path-based and are not atomic with the subsequent mutation. In particular, after `ensure_workspace()` has validated and resolved the path, another process can replace the root/workspace component before `shutil.rmtree()` runs; the cleanup then operates on a name th
**competitive_app/src/competitive_app/adapter/out/sandbox/protocol.py:182-182** [bug] `decode_request()` accepts arbitrary decoded JSON, but `from_mapping()` converts it with `dict(value)` before `_validate_request()` can check that it is an object. A scalar raises `TypeError`, and an array can raise `ValueError`/`TypeError`; `run_worker()` only catches `RpcProtocolError` and `Worker
  - 建议：request = _validate_request(value)
**competitive_app/src/competitive_app/adapter/out/sandbox/sandbox.py:85-88** [security] The terminal frame returned by the runtime is not passed through the masking path used by `deliver`. `NativeRuntime` returns the same final frame after invoking the callback, and `SandboxToolExecutor` reads `terminal.result`/`terminal.error` directly, so sensitive paths or other strings in the final
  - 建议：terminal = await self._runtime.execute_worker(             request, deliver, command=command, signal=signal         )         masked = _mask_value(terminal.to_m
**competitive_app/src/competitive_app/adapter/out/sandbox/sandbox_tool_executor.py:84-86** [security] The terminal frame returned here is the unmasked frame from `Sandbox.execute_worker`: that facade applies `mask_output` only to frames passed through `on_frame`, while `NativeRuntime.execute_worker` returns its original terminal frame. Consequently, secrets in a final tool result/details bypass the 

### competitive_app application / domain

**competitive_app/src/competitive_app/application/evolution/evolution_manager.py:70-76** [bug] If `accept_candidate` completes (or writes the scope/manifest) and a later operation in this `try` fails, this handler only rolls back SQLite. `SQLiteSkillStore.rollback` does not remove the candidate file, clear its scope metadata, or regenerate `package.json`, so the projected active skill files c
**competitive_app/src/competitive_app/application/evolution/parser.py:132-134** [bug] The existing installation is deleted before the source is validated or the replacement is copied and parsed. If `source_dir` is missing/unreadable, lacks `SKILL.md`, or copying/parsing fails, this leaves the destination absent (and `source_dir == destination` can also destroy the source). Stage and 
**competitive_app/src/competitive_app/application/model/router.py:173-180** [bug] This emits every registered provider as `openai-completions`, but the provider factories do not share that protocol: `openai` and `openai-codex` expose response APIs, while `opencode` can require different APIs per catalog model. The agent resolves the stream implementation from this `api` field, so
**competitive_app/src/competitive_app/application/workflow/extraction.py:134-146** [bug] The drain is skipped whenever `_run_subagent_prompt` is cancelled or raises out of the surrounding `try`: `intake.flush()` is executed only after the prompt returns normally, while the `finally` block only shuts down the harness. Thus fetched pages buffered before a cancellation/uncaught prompt fail
**competitive_app/src/competitive_app/application/workflow/runtime_registry.py:106-106** [bug] `get_stream()` can return `None` here: the task's runner done callback removes `_streams` as soon as the task completes, and this endpoint can observe a previously non-terminal `task_status` after that callback runs (or a pending task from before this process). The next `q.get()` then raises `Attrib
**competitive_app/src/competitive_app/application/workflow/session_service.py:138-138** [bug] Queued prompts are never registered with `RuntimeRegistry.register_queued`, so `RuntimeRegistry.abort_session()` cannot cancel them despite the documented F-A11 behavior. A second prompt blocked in this `wait_for(lock.acquire())` remains queued, can acquire the lock and execute after an abort, and t
**competitive_app/src/competitive_app/application/workflow/task_service.py:937-941** [bug] `run_cycle()` is part of the post-task bookkeeping, but it is inside the same `try` as the actual research run. If the evolution manager/ratchet raises after `runner.run()` has completed successfully, this outer handler updates the task to `failed`, overwriting the successful status and hiding the c
**competitive_app/src/competitive_app/application/workflow/task_service.py:937-941** [bug] `run_cycle()` is executed inside the same `try` as the research run, so an exception from this optional post-task evolution hook is caught by the outer handler and changes the task to `failed` even when `runner.run()` already returned `completed`. This makes successful reports disappear from complet

### competitive_app observability / persistence

**competitive_app/src/competitive_app/adapter/out/observability/__init__.py:65-67** [security] The redaction policy does not cover common credential representations whose key names are not exact matches or underscore suffixes. For example, a journal payload such as `{"headers": {"X-Api-Key": "..."}}` or `{"accessToken": "..."}` reaches the recursive branch unchanged (`x-api-key` and `accessto
**competitive_app/src/competitive_app/adapter/out/observability/run_journal.py:42-42** [bug] This is labeled and consumed as JSONL, but `indent=2` serializes each event across multiple lines (and adds an extra blank line). Any line-oriented reader will see invalid/incomplete JSON instead of one event per line, so the journal cannot be parsed as JSONL. Serialize compactly without indentation
  - 建议：file.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
**competitive_app/src/competitive_app/adapter/out/persistence/task_projection_store.py:566-566** [bug] `EvidenceNode.id` is only an 8-hex UUID suffix (and callers can provide arbitrary IDs), so it is not guaranteed to be globally unique across tasks. Because `evidence_id` is the global primary key and this uses `INSERT OR REPLACE`, indexing a node whose ID already exists for another task deletes/repl

### frontend

**frontend/src/hooks/useTaskStream.ts:29-31** [bug] These asynchronous reads are not tied to the effect instance. If `taskId`/`query` changes or the hook unmounts while the initial request or a polling request is in flight, its continuation can call `applyTask` after the next `reset`; `applyTask` does not validate the task ID or event ordering, so a 
**frontend/src/lib/api.ts:25-25** [bug] This shared fallback is also used for mutating requests, so HTTP 4xx/5xx and network failures are converted into fabricated success responses (for example `createTask` returns a demo ID, `submitClarify`/`submitFeedback` return `ok: true`, and `deleteSubscription` returns `ok: true`). Callers then na
**frontend/src/pages/EvidencesPage.tsx:149-153** [security] `source`/`source_url` originates from stored evidence data and is assigned directly to `href`. If an imported or API-provided value is `javascript:` (or another executable scheme), clicking this link can execute script in the app's origin. Validate/allowlist URL schemes (for example, only `http:` an
**frontend/src/pages/GraphPage.tsx:150-154** [security] `source` is ultimately populated from model/tool evidence and is not constrained to an HTTP(S) URL by this page or the API contract. Assigning it directly to `href` allows a `javascript:` (or other active scheme) value to execute when the user clicks the link. Validate/allowlist the URL scheme befor
**frontend/src/pages/ReportPage.tsx:180-183** [security] `src` is rendered directly as an anchor URL. Because these values originate from report/evidence data, a stored or compromised value such as `javascript:...` can execute when the user clicks the link. Validate/normalize the URL before rendering (for example, allow only `http:` and `https:` schemes a
**frontend/src/store/taskStore.ts:31-32** [bug] `ingest` does not verify the event's `task_id` (the backend includes it in snapshot and terminal/event payloads) against the current `taskId`. Because `useTaskStream` starts `fetchTask(...).then(...)` and opens a new EventSource without cancelling/guarding the previous request's callbacks, a delayed

### capability_packages / misc

**.dockerignore:5-5** [bug] This pattern excludes every directory named `vendor` from the Docker build context, including the newly added `competitive_app/src/competitive_app/adapter/out/sandbox/native/vendor/seccomp` tree. The native Linux sandbox resolves and verifies `apply-seccomp` from that vendored path, so a container b
  - 建议：# Ignore unrelated vendored dependencies, but keep the sandbox's pinned helper binaries in the build context. # vendor
**capability_packages/pi_auto_review/extensions/register.py:50-50** [security] `_RUNTIME` is process-global and `bind_runtime()` has no owner/session scope or replacement cleanup (the only `_unbind_runtime()` is never invoked here). Any subsequent harness/session that reuses this extension can therefore inherit the previous model registry and transcript/signal/audit callbacks;
  - 建议：# Keep runtime dependencies scoped to the installed/session extension, not a process-global dict. _RUNTIME: dict[str, Any] = {}
**capability_packages/pi_auto_review/pi_auto_review/reviewer.py:430-433** [bug] For a provider-qualified reference such as `provider/model`, this lookup filters only by `id`, so an earlier model with the same ID from a different provider can be selected and then passed to `getAuth`/`completeSimple`. The requested provider is not verified; filter by both `candidate["provider"] =
**capability_packages/search_tavily/extensions/tavily_tools.py:250-253** [security] The fetch tool advertises a full HTTP/HTTPS URL, but this validation accepts any non-empty string and forwards it to Tavily. A model/user can therefore submit unsupported schemes or internal/metadata targets; because Tavily performs the extraction remotely and returns the fetched content, this can b
  - 建议：url = _as_str(params.get("url")).strip()     parsed = urllib.parse.urlparse(url)     if parsed.scheme not in {"http", "https"} or not parsed.netloc:         rai
**capability_packages/search_tavily/extensions/tavily_tools.py:268-269** [security] `follow_redirects=True` applies to the POST carrying `api_key` in its JSON body. A 307/308 redirect can preserve the POST body while redirecting to a different host, disclosing the Tavily credential to that destination (including if the provider endpoint is compromised or misconfigured). Do not foll
  - 建议：async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:             _check_aborted(signal)
**competitive_app/src/competitive_app/adapter/in_/fastapi/routes_reports.py:22-25** [security] These report endpoints have no authentication or ownership check, and the application does not install a global auth dependency. When the FastAPI server is reachable by more than the trusted local user, any caller can enumerate report cards/task IDs, read another task's report, invoke its LLM-backed
**competitive_app/src/competitive_app/adapter/in_/fastapi/routes_tasks.py:185-185** [bug] `RuntimeRegistry.get_stream()` returns the single per-task queue, not a per-client subscription. Consequently, two concurrent SSE clients call `q.get()` on the same queue and each consumes a different subset of events; one client can miss the terminal `done`/`error` and remain open indefinitely. The
**scripts/fetch_upstream.sh:11-13** [bug] When the script is invoked with no arguments, `${@:-ai agent coding-agent}` expands to one array element containing the literal string `ai agent coding-agent`, not three package names. The loop therefore passes a single invalid sparse-checkout path (`packages/ai agent coding-agent`) and the default 
  - 建议：if (( $# == 0 )); then   PACKAGES=(ai agent coding-agent) else   PACKAGES=("$@") fi SPARSE_PATHS=() for p in "${PACKAGES[@]}"; do

## 4. 非问题项

- ⚠️ **误报** `sandbox/native/seccomp.py:100-103`——`native/vendor/seccomp/<arch>/apply-seccomp` 是 npm 发布二进制 + SHA-256 pin（P3.3 plan §2.3 / G0 map §5.1），`seccomp-src/` 仅为 provenance 源码；二进制缺失时 fail-closed + 降级日志（linux.py:1058）。
- 📌 **故意 stub** `packages/agent/.../harness/tools/edit.py:7`——P2 module map 标 `host-delta | stub; not required for exit smoke`；bash.py/image.py/edit_diff.py 等同理。

## 4.5 packages/ai 定性结论（2026-08-04 人工核实，对照上游 main）

上游 `earendil-works/pi` main 对以下文件**均有完整实现**（openai-responses.ts 366 行真 Responses API、google-generative-ai.ts 523 行真 Gemini 流、openrouter-images.ts 真调 OpenRouter、cloudflare-workers-ai.ts 用 cloudflareWorkersAIAuth + cloudflareStreams、radius.ts 为 dynamic catalog + refreshModels）。本仓对应文件经核实分三类：

### 🎯 A. 有意 host-delta（10 条，移出 known-issues）

API 层转发到 openai-completions transport 是 **P1 期刻意的 pragmatic parity**，代码注释 + module map 双重记录：
- `api/openai_responses.py:22`——注释："isomorphic surface delegates to chat completions-compatible streaming ... host-delta pragmatic parity for P1 CI"；map：`surface; chat-compat streaming path`
- `api/google_generative_ai.py:10`——注释："Host-adapted: Google native SSE can be expanded; structural module exists."；map：`structural; shared http path`
- `api/azure_openai_responses.py`、`api/bedrock_converse_stream.py`（map: structural）、`api/google_vertex.py`、`api/mistral_conversations.py`、`api/openai_codex_responses.py`——同模式转发
- `providers/openai.py:16`、`providers/xai.py:19`、`providers/google.py:16`——走上述 api，同源有意

> 治理注记：这些偏差记录在**代码注释 + module map notes**，但未走 ADR（ADR 只背书了 0012/0015）。若要长期成立，建议补一条 ADR 或在 P1 完成声明中固化。

### ⛔ B. 移植欠账（9 条，owner 2026-08-04 拍板：范围外，不修）

上游有实现，本仓为壳/stub；**已确认不在 CompetitorLens 支持范围**，从 known-issues 移除：
- `api/openrouter_images.py:7`——恒返回 `stopReason:"error"`，从不调 provider
- `providers/cloudflare_workers_ai.py` ×2 / `cloudflare_ai_gateway.py`——auth resolver 恒空；baseUrl 占位符未替换
- `providers/azure_openai_responses.py:10`——无 endpoint/deployment/API version
- `providers/google_vertex.py:16`——ambient 凭证解析为空
- `providers/github_copilot.py:20`——认证方式不符
- `providers/radius.py:16`——models 空、无 refreshModels
- `providers/anthropic.py:14`——`ANTHROPIC_OAUTH_TOKEN` 被当 x-api-key 发送

> 若未来产品需要以上任一 provider，从上游移植对应实现即可（上游均有现成 TS 参考）。

### 🔴 C. 真 bug（7 条，known-issues 保留）

与兼容策略无关的代码缺陷：`api/openai_completions.py:44-57` ×2（异常逃逸 → 消费者永久阻塞；**影响默认 openai-compat 路径**）、`api/google_shared.py:27-36` ×2（toolResult/toolCall 转换丢弃；当前 google 走 compat 故不可达，原生扩展时会踩）、`auth/credential_store.py:30`（None-as-delete 竞态）、`providers/faux.py:490`（无 loop 时挂起）、`api/anthropic_messages.py:38`（payload 构造在 try 外）。

## 5. Medium 统计（220）

| 文件 | 条数 |
|---|---|
| `frontend/src/pages/TracePage.tsx` | 5 |
| `competitive_app/src/competitive_app/application/evolution/eval/analyzers/skill_judgment_analyzer.py` | 4 |
| `competitive_app/src/competitive_app/application/workflow/task_service.py` | 4 |
| `competitive_app/src/competitive_app/domain/socm/frontier.py` | 4 |
| `frontend/src/pages/LibraryPage.tsx` | 4 |
| `competitive_app/src/competitive_app/adapter/out/persistence/socm_store.py` | 3 |
| `competitive_app/src/competitive_app/adapter/out/sandbox/approval/sandbox.py` | 3 |
| `competitive_app/src/competitive_app/adapter/out/sandbox/native/broker.py` | 3 |
| `competitive_app/src/competitive_app/adapter/out/sandbox/native/runner.py` | 3 |
| `competitive_app/src/competitive_app/application/evolution/eval/analyzers/checks.py` | 3 |
| `competitive_app/src/competitive_app/application/model/fallback_stream.py` | 3 |
| `competitive_app/src/competitive_app/application/workflow/coverage_engine.py` | 3 |
| `competitive_app/src/competitive_app/application/workflow/extraction.py` | 3 |
| `competitive_app/src/competitive_app/application/workflow/runtime_registry.py` | 3 |
| `competitive_app/src/competitive_app/wiring.py` | 3 |
| `frontend/src/index.css` | 3 |
| `frontend/src/pages/DashboardPage.tsx` | 3 |
| `frontend/src/pages/EvidencesPage.tsx` | 3 |
| `frontend/src/pages/ReportPage.tsx` | 3 |
| `frontend/src/pages/WorkspacePage.tsx` | 3 |
| `packages/agent/src/earendil_works/pi_agent/harness/skills.py` | 3 |
| `packages/ai/src/earendil_works/pi_ai/api/_http_stream.py` | 3 |
| `packages/ai/src/earendil_works/pi_ai/models.py` | 3 |
| `scripts/comparison_experiment.py` | 3 |
| `capability_packages/pi_auto_review/pi_auto_review/policy.py` | 2 |

Medium bug/security 已全量纳入 known-issues P2（159 条）；此处仅剩 maintainability/performance/other 的分布参考。其余主题：异步竞态/取消处理、SQLite 事务与回滚、Pydantic 校验缺口、前端类型漂移、evolution 度量与 gate。

## 6. 已知边界

- LLM 生成，未逐条人工核实；定位以原始 JSON 的 `start_line/end_line` + `thinking` 为准。
- packages/ai 集群已人工核实（§4.5）；sandbox 安全条目仍建议人工复核。
