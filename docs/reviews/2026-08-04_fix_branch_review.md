# OCR Review — fix/known-issues-2026-08-04（2026-08-04）

> 工具：`open-code-review` v1.8.6 · 模型 gpt-5.6-luna（pro3）
> 模式：workspace（staged + unstaged + untracked，排除 `docs/reviews/**`）· run_id `acdb1518-7cdf-4a01-8e53-0a57d09efb40`
> 数据源：`docs/reviews/2026-08-04-fix-branch-raw.json`（可 `ocr review --resume acdb1518-7cdf-4a01-8e53-0a57d09efb40` 续跑）
> 统计：160 文件 / 89 finding / 11,380,424 tokens / 耗时 22m44s

**11 high / 56 medium / 22 low**

## High（11）

### high-1 `competitive_app/src/competitive_app/adapter/out/sandbox/approved_registry.py:43-44`

This default approval path trusts the module-name prefix (and the later parent-name check) rather than verifying the resolved module is under the repository's actual trusted `capability_packages` directory. A shadowed package on `sys.path`, or a module loaded from `/tmp/capability_packages/...`, is therefore approved and can cross the host/worker tool trust boundary. Resolve the configured repository capability root and require `resolved.is_relative_to(trusted_root)` (and apply the same check to `capability_packages.*` names) instead of matching only a directory name/prefix.

### high-2 `competitive_app/src/competitive_app/adapter/out/sandbox/native/broker.py:99-99`

`writer.write()` only appends the request to asyncio's buffer; without `await writer.drain()` the small network-request message may remain buffered while this coroutine waits for the parent's response, so the parent never sees the request and the proxy hangs until the request times out. Keep the drain before awaiting `future`.

```python
await writer.drain()
        allowed = bool(await future)
```

### high-3 `competitive_app/src/competitive_app/adapter/out/sandbox/native/policy.py:284-284`

On Linux this adds `DARWIN_SECRET_DENY_WRITE_GLOBS` (including `**/.env.*` and `**/*.pem`) to every default policy, but the Linux SRT manager explicitly raises `ValueError` for any `denyWrite` glob in `_get_fs_write_config`. Consequently, default sandbox initialization fails before a command can run on Linux rather than merely failing closed. Keep these globs Darwin-only, or implement a Linux-compatible expansion/enforcement mechanism before adding them here.

### high-4 `competitive_app/src/competitive_app/adapter/out/sandbox/native/native_sandbox_provider.py:89-94`

`O_NOFOLLOW` prevents a symlink at this name, but it does not prevent an existing hard link. A worker that can write the workspace can replace `approved_tools.json` with a hard link to another file owned by the same UID; this `O_TRUNC` then truncates that outside file before copying the manifest, creating a host-file destruction primitive. Remove the destination via the directory fd and recreate it with `O_CREAT | O_EXCL` (and handle an existing destination/retry), so an attacker-created link is rejected rather than opened/truncated.

```python
try:
            os.unlink(destination.name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        file_fd = os.open(
            destination.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
```

### high-5 `competitive_app/src/competitive_app/adapter/out/sandbox/native/srt/process.py:197-201`

If the caller cancels `ripgrep` while it is awaiting `asyncio.wait(...)` (the `abort_signal` path), cancellation does not propagate to either task in the wait set. This `finally` only cleans up `abort_task`, so `wait_task` continues waiting on `process.communicate()` and the subprocess can remain alive, leaking a process/pipes and potentially outliving the request. Cancel and await `wait_task` here as well (after killing the process if needed).

```python
finally:
        if abort_task is not None and not abort_task.done():
            abort_task.cancel()
        if abort_task is not None:
            await asyncio.gather(abort_task, return_exceptions=True)
        if not wait_task.done():
            _kill_process(process)
            wait_task.cancel()
        await asyncio.gather(wait_task, return_exceptions=True)
```

### high-6 `competitive_app/src/competitive_app/adapter/out/sandbox/native/workspace.py:84-84`

The `O_NOFOLLOW` checks only protect these opens; both descriptors are closed before the returned `Path` is consumed. `NativeSandboxProvider.acquire()` subsequently stages the manifest into this path and passes it to `NativeRuntime`, which later reopens it by name, so a process able to modify the workspace root can replace the validated `<scope_id>` entry (or a parent component) between validation and use and redirect host-side operations outside the intended workspace. Keep/use a directory descriptor for subsequent operations (including staging and process `cwd`/policy construction), or otherwise make all later access descriptor-relative; a one-time path check cannot provide the claimed race-resistant boundary.

### high-7 `competitive_app/src/competitive_app/adapter/out/sandbox/native/srt/proxy.py:818-821`

A negative `Content-Length` passes this check, so `_read_body` returns an empty body while leaving any following bytes unread and `_handle_request` forwards the original negative header upstream. Reject negative lengths as a malformed request (and similarly avoid silently accepting invalid values), rather than treating them as an empty body; otherwise the proxy can emit an invalid/desynchronized request and obscure request-framing failures.

```python
if length < 0:
            raise ValueError("invalid negative Content-Length")
        if length > MAX_REQUEST_BODY_SIZE:
            raise RequestBodyTooLarge(
                f"request body exceeds {MAX_REQUEST_BODY_SIZE} bytes"
            )
```

### high-8 `competitive_app/src/competitive_app/application/evolution/evolution_manager.py:54-58`

If `create_version` succeeds but `accept_candidate` fails, a failed `rollback` is silently ignored and `run_context` returns `None`; the newly created candidate can therefore remain active in the store despite there being no evolution record (and no error is surfaced). This fail-closed path should not suppress rollback failure—either retry/raise an explicit recovery error or otherwise guarantee the active pointer is restored before returning.

### high-9 `competitive_app/src/competitive_app/application/evolution/skill_files.py:34-37`

Writing the manifest before the marker and scope projection reverses the dependency ordering: after `create_version`, `list_active()` already includes this candidate, so `_write_manifest_locked()` publishes a manifest referencing it before either `.skill_id` or scope metadata exists. If the subsequent `write_text()`/`set_scope()` fails or the process stops between these operations, the manifest permanently points at an incomplete skill projection. Write the marker and scope metadata first, then publish the manifest (or make all three projections transactional/recoverable).

### high-10 `competitive_app/src/competitive_app/domain/socm/frontier.py:169-172`

The reverse subset match drops work from the newly added task: when an active task targets `e.a` and a new task targets `e.a` plus `e.b`, `add()` returns the narrow existing task without adding `e.b` anywhere. Consequently `e.b` is never dispatched or covered. Deduplication can safely collapse an incoming subset into an existing superset, but an incoming superset must either be retained/merged into the existing task (including its target cells) or not be treated as a duplicate.

### high-11 `competitive_app/src/competitive_app/wiring.py:730-730`

When `config.sandbox.config` is empty (the normal default), this now automatically reads a user-controlled file and turns its absolute paths into sandbox `allowRead` entries. An account/user-controlled `~/.pi/agent/extensions/pi-sandbox/config.json` can therefore grant the worker access to arbitrary host files (for example `/etc/...` or other sensitive paths) without an explicit application configuration/opt-in. This changes the previous fail-closed behavior and is especially risky because the file is outside the workspace policy. Keep the empty-path case returning `[]`, or require an explicit trusted configuration path and validate it against an approved location.

```python
if not path:
        return []
    config_path = Path(path).expanduser()
```

## Medium（56）

### medium-1 `capability_packages/pi_auto_review/pi_auto_review/policy.py:274-275`

Redaction is applied after `bounded_string`, so a long argument can be truncated in the middle of a credential before the redaction regex sees it. In particular, a private key whose `BEGIN` marker is outside the retained prefix (or whose footer is outside the suffix) will not match and key material can still be sent to the classifier. Redact the full serialized value first, then bound the redacted result, matching `_result_text`'s ordering.

```python
arguments = bounded_string(_redact_sensitive_result(bounded_string(part.get("arguments") or {})))
        out.append(f"{part['name']} {arguments}")
```

### medium-2 `competitive_app/src/competitive_app/adapter/out/persistence/socm_store.py:99-101`

`_cross_process_lock()` performs a blocking `fcntl.flock(LOCK_EX)` while this `async def` holds the event-loop thread. If another process is in a read/modify/write section, `delete()` can block the entire event loop until that process releases the lock, stalling unrelated requests/tasks. Acquire the cross-process lock off the event loop (or use a non-blocking/polling strategy) before entering the async critical section.

### medium-3 `capability_packages/pi_auto_review/pi_auto_review/policy.py:274-275`

Redaction is applied after `bounded_string`, so a long argument can be truncated in the middle of a credential before the redaction regex sees it. A private key whose BEGIN marker or footer is outside the retained prefix/suffix will not match, allowing key material into classifier input. Serialize/redact the complete value first and only then apply the evidence bound.

```python
raw_arguments = part.get("arguments") or {}
        try:
            serialized_arguments = raw_arguments if isinstance(raw_arguments, str) else json.dumps(raw_arguments)
        except (TypeError, ValueError):
            serialized_arguments = "[unserializable]"
        arguments = bounded_string(_redact_sensitive_result(serialized_arguments))
        out.append(f"{part['name']} {arguments}")
```

### medium-4 `competitive_app/src/competitive_app/adapter/in_/fastapi/routes_tasks.py:151-152`

The subscriber queue is added to `_subscribers` but there is no corresponding removal when the SSE generator disconnects (including the normal `request.is_disconnected()` path or cancellation). Every reconnect therefore leaves an unbounded queue retained by the fanout; for a long-running task the module-level `_SSE_FANOUTS` also retains the fanout and its pump, and future events continue to be enqueued for abandoned clients. Return a subscription handle/unsubscribe callback and invoke it from an `event_gen` `finally` block, and stop/remove an idle fanout when its subscriber set becomes empty.

### medium-5 `competitive_app/src/competitive_app/adapter/in_/fastapi/routes_tasks.py:222-226`

This turns an infrastructure/read failure while constructing the snapshot into a task-level `failed` SSE event and closes the stream, without changing the task's persisted status. For example, a transient SOCM store/database failure can make the client display a failed task and stop receiving events even though the workflow is still running or later succeeds. The event should use a distinct snapshot/infrastructure error contract (or retry/fall back while retaining the actual task status), rather than reporting `status: failed`.

### medium-6 `competitive_app/src/competitive_app/adapter/in_/fastapi/routes_tasks.py:171-175`

`RuntimeRegistry.get_stream()` already creates and registers a new subscriber queue in `_TaskStream`; this queue becomes the fanout's `_source` here, but `_QueueFanout` never unregisters it. Thus every fanout (including ones recreated after cleanup) leaves a queue in the registry's `subscribers` set, and `publish_stream()` continues enqueuing into abandoned source queues. The route-level cleanup must also unsubscribe the source queue (or expose a registry subscription/fanout abstraction with explicit removal).

### medium-7 `competitive_app/src/competitive_app/adapter/out/sandbox/approved_registry.py:51-52`

`importlib.import_module()` executes the target module's top-level initialization, which can raise arbitrary exceptions (for example `ValueError` or a capability-specific configuration error). This helper is used during registry construction/validation, so such an exception escapes instead of treating the target as unavailable/unapproved, allowing a malformed or hostile loader alias to crash startup. Handle the import failure consistently with `_imported_target_callable` (or catch `Exception` and return `False`, preserving the cause only if it is surfaced to the caller).

### medium-8 `capability_packages/pi_auto_review/extensions/register.py:87-89`

This fallback is unsafe when cleanup runs from a different task/context (or after a newer binding): `reset(token)` cannot operate there, so `_RUNTIME.set(None)` clears whatever runtime is currently active in that context rather than the binding owned by this callback. A stale teardown callback can therefore remove another session's dependencies and cause subsequent reviews to fail or use context fallbacks. Do not mutate the current context on `ValueError`; instead make cleanup idempotent/owner-aware, or arrange for cleanup to execute in the context where the token was created.

### medium-9 `competitive_app/src/competitive_app/adapter/out/sandbox/approval/sandbox.py:35-36`

`requested_path` is copied into the `BoundaryRequest` without validating its type. Although the trap type documents this field as a string, this converter is fed runtime trap data; a truthy non-string value is coerced into the ID/resource f-string but remains (for example) an integer in `path`, violating the `BoundaryRequest` contract and potentially breaking downstream policy matching/serialization. Reject non-string `requested_path` values (or only accept `None`/a non-empty string) before constructing the request.

```python
requested_path = trap.get("requested_path")
        if requested_path is not None and (
            not isinstance(requested_path, str) or not requested_path
        ):
            raise ValueError("sandbox filesystem requested_path must be a non-empty string")
        resource = f"{requested_path}:{resolved_path}" if requested_path else resolved_path
```

### medium-10 `competitive_app/src/competitive_app/adapter/out/sandbox/approval/sandbox.py:28-30`

Only checking that `operation` is a non-empty string allows arbitrary operation names through. For filesystem traps every value other than `read` is mapped to the `filesystem-write` surface, so an unknown operation can be presented to policy/approval as a write request rather than being rejected; this is an unsafe and misleading authorization classification. Validate the per-kind allowlists explicitly (`read`/`write` for filesystem and `connect`/`bind` for network).

```python
operation = trap.get("operation")
    allowed_operations = {
        "filesystem": {"read", "write"},
        "network": {"connect", "bind"},
    }[kind]
    if operation not in allowed_operations:
        raise ValueError(f"unsupported sandbox {kind} operation: {operation!r}")
```

### medium-11 `competitive_app/src/competitive_app/adapter/out/sandbox/protocol.py:211-211`

This removes the documented `Mapping[str, Any]` support from `encode_request`: `_validate_request` only accepts an actual `dict`, so callers passing `MappingProxyType`, a read-only mapping, or another custom `Mapping` now receive `invalid_shape` instead of being encoded as before. Keep the `dict(request)` normalization (or make `_require_object` accept `Mapping`) while retaining validation of the copied data.

### medium-12 `competitive_app/src/competitive_app/application/workflow/task_service.py:247-249`

`_repo.create()` allocates the JSONL session (and may eagerly create related workspace state), but both `get_metadata()` and extraction of `meta["id"]` occur before the compensating `try`. If metadata retrieval raises after creation, `_cleanup_created_session()` is never invoked, leaving the newly allocated session and any associated artifacts orphaned. Move metadata acquisition into the guarded transaction or add an outer cleanup path that can clean up using the session object.

### medium-13 `competitive_app/src/competitive_app/application/workflow/task_service.py:303-305`

Rollback is implemented as an unconditional delete followed by recreation. A concurrent task operation can observe the row missing or update the row between these statements; the recreation then overwrites that update and also loses fields not copied here (for example, the original timestamps). Use an atomic/conditional restore operation, or serialize this transition with the same task-level coordination used by other mutations.

### medium-14 `competitive_app/src/competitive_app/domain/socm/coverage.py:213-213`

When a weak cell is retried and the judge returns the same value with a stronger confidence, this path raises `cell.confidence` via `max(...)` but leaves `cell.source` and `cell.source_excerpt` pointing to the earlier weaker result. The matrix/report will therefore present the stronger confidence alongside stale provenance, misrepresenting which evidence supports the accepted value. When the new confidence exceeds the current one, update the provenance as well (or retain the stronger candidate explicitly).

### medium-15 `competitive_app/src/competitive_app/application/workflow/coverage_engine.py:374-380`

This read/check followed by `save()` is not an atomic read-modify-write. `SocmStore` explicitly documents that `load()` + `save()` is unsafe for RMW, and its cross-process lock only protects each individual operation. If two coverage runs/workers for the same session (including separate processes) enter this method concurrently, both can observe the same remaining allowance and both consume it, exceeding `max_queries` and dispatching searches beyond the configured cap. Use `atomic_update()` for the check and increment as one operation (and base dispatch allowance on its result).

### medium-16 `competitive_app/src/competitive_app/application/workflow/coverage_engine.py:362-366`

A completed sub-agent task can fail before producing evidence (for example, ephemeral harness construction or shutdown-related execution), but this handler only logs the exception and the scheduler continues/refills. The coverage loop then evaluates the round as if that subtask had been processed and can terminate successfully based on other cells, yielding a successful search result with silently missing coverage. Record the subtask as failed/incomplete (or propagate the failure so the search stage cannot report success) rather than treating every exception as a recoverable success.

### medium-17 `competitive_app/src/competitive_app/application/workflow/extraction.py:170-170`

This dictionary collapses multiple observations with the same source URL to the last page's text. If the fetch tool submits the same URL more than once (for example, separate result chunks or repeated fetches), a judge citation whose verbatim excerpt occurs in an earlier observation is rejected here even though that observation was included in `pages_blob`, so valid evidence is silently marked UNKNOWN. Preserve all texts per source and accept the excerpt if it occurs in any of them.

```python
source_pages: dict[str, list[str]] = {}
        for txt, src in observations:
            key = str(src).strip()
            if key:
                source_pages.setdefault(key, []).append(txt)
```

### medium-18 `competitive_app/src/competitive_app/application/workflow/session_service.py:151-154`

Cancellation can arrive after `lock.acquire()` has acquired the lock but before this task resumes from `wait_for`. In that case the `CancelledError` is converted to `SessionAbortedError` and execution skips the later `finally` that releases the lock, leaving the per-session lock permanently held and causing every subsequent prompt to time out. Track whether acquisition succeeded and release on cancellation (or put acquisition and prompt/release under one cancellation-safe ownership `try/finally`).

### medium-19 `competitive_app/src/competitive_app/domain/socm/strategy.py:111-113`

`_check_amount` validates the increment but not the result of the addition. Two individually finite wall-clock values near `1e308` can make `consumed_wall_seconds` become `inf`; the model then violates the finite-value invariant and `ratio()` silently returns `inf`, exhausting the budget permanently. Validate the post-addition total (or reject additions that would overflow) before mutating the counter.

```python
def consume_wall(self, seconds: float) -> None:
        self._check_amount(seconds, "wall-clock consumption")
        total = self.consumed_wall_seconds + seconds
        if not isfinite(total):
            raise ValueError("wall-clock consumption exceeds finite range")
        self.consumed_wall_seconds = total
```

### medium-20 `competitive_app/src/competitive_app/application/workflow/runtime_registry.py:27-30`

Subscriber queues are never removed when an SSE generator disconnects, and `asyncio.Queue()` is unbounded. A slow/disconnected client therefore remains in `subscribers` and continues accumulating every event; because completed streams are also retained in `_streams`, repeated task streams can grow memory indefinitely. Add an unsubscribe/finally path and bound or backpressure subscriber queues (and evict completed streams after the late-subscription window).

### medium-21 `competitive_app/src/competitive_app/application/workflow/runtime_registry.py:135-137`

This unconditionally replaces the task's stream. Concurrent clarify submissions/resumes can both pass the earlier active check; the later startup then replaces the stream while the first runner/subscribers still use it, and its rollback can unregister that replacement. The first runner's terminal events can consequently be dropped and attached SSE clients can hang. Reuse an existing stream or serialize registration/startup per task, and only remove the stream owned by the corresponding startup.

### medium-22 `competitive_app/src/competitive_app/application/workflow/runtime_registry.py:159-163`

The previous implementation swallowed ordinary task exceptions here, but this change only catches `CancelledError`. If the runner finishes with an exception after the `done()` check (or cancellation is not honored and the runner fails), awaiting it propagates that exception from the abort API instead of returning the established boolean result. Catch/handle runner exceptions consistently with the prior contract while preserving cancellation diagnostics.

### medium-23 `competitive_app/src/competitive_app/wiring.py:528-539`

This rollback helper is only invoked by the `try` beginning at `TaskService` construction below. Exceptions during the preceding service-composition code (for example fallback-chain construction, `SessionService`, judge resolution, or evolution setup) still exit `build_application_state` with the already initialized stores and sandbox lifecycle open. Startup failure can consequently leak SQLite connections and/or the sandbox provider. The cleanup scope should cover all code after resource acquisition, not just `TaskService`/`ApplicationState` construction.

```python
async def _rollback_resources() -> None:
        """Close resources opened before service composition fails."""
        if sandbox_lifecycle is not None:
            try:
                await sandbox_lifecycle.shutdown()
            except Exception:
                pass
        for resource in (workflow_skill_store, skill_store, store):
            try:
                await resource.close()
            except Exception:
                pass

    try:
        # compose all services and return ApplicationState inside this scope
        ...
    except BaseException:
        await _rollback_resources()
        raise
```

### medium-24 `frontend/src/hooks/useTaskStream.ts:43-43`

This update can apply an out-of-order HTTP snapshot over newer SSE state. The initial `fetchTask` starts before the EventSource, so a delayed GET response may resolve after `state_snapshot`/progress/terminal events and `applyTask` will blindly replace the store's stages, coverage, and status-derived flags. `isCurrent()` only checks task identity, not response freshness. Track an event/version sequence (or make `applyTask` reject stale snapshots) before applying GET results; otherwise progress can visibly regress or a terminal state can be overwritten.

### medium-25 `frontend/src/pages/LibraryPage.tsx:50-53`

`resumeTask` now propagates HTTP/network errors because its fallback was removed in `api.ts`, but this handler only uses `finally`; a failed resume therefore becomes an unhandled rejection with no user-visible feedback. Catch the error (and ideally show a toast/message) so the user knows the resume failed rather than silently remaining on the library page.

### medium-26 `frontend/src/lib/api.ts:32-36`

Removing the fallback makes `createTask` reject on network/HTTP/JSON failures. `HomePage.submit` still navigates in its `finally` block, so a failed request sends the user to `/workspace/undefined` and leaves the rejection unhandled. Either handle the error before navigation (and show a user-facing message) or preserve an explicit failure result.

### medium-27 `frontend/src/lib/api.ts:44-51`

This change also makes clarification submission reject, but `ClarifyPage.go` navigates unconditionally from `finally`. A failed POST therefore still opens the workspace even though clarification was not accepted, and the rejected promise is not handled. Navigate only after a successful response and provide an error path.

### medium-28 `frontend/src/lib/api.ts:44-51`

The mutation callers for these newly non-fallback APIs are not uniformly updated: `DashboardPage.addSub`, `delSub`, and `runSub` await them without `try/catch` or `finally`. A failed request can become an unhandled rejection; for `runSub`, `setRunning(null)` is skipped and the button remains stuck. Keep the fallback or make each caller reset state and display an error on rejection.

### medium-29 `frontend/src/lib/api.ts:122-129`

`ReportPage.doRefine`, `doFeedback`, and `WorkspacePage.onAbort` also await the now-rejecting helpers without error handling. On a failed refine, `setRefining(null)` and the reload are skipped, leaving the section permanently in a refining state; failed feedback/abort requests likewise produce unhandled rejections and no user-facing error. These callers need `try/catch/finally` around the new rejection behavior.

### medium-30 `frontend/src/pages/EvidencesPage.tsx:51-53`

`fetchEvidences` can reject (the API helper rethrows network/HTTP errors), but this chain has no rejection handler. That leaves an unhandled promise rejection and provides no error state or user-facing feedback; the page can continue displaying stale evidence while loading simply stops. Add a cancellation-aware `.catch(...)` that records/clears the error (or at least handles the failure) before `finally`.

```python
.catch(() => {
        if (!cancelled) setData(EMPTY)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
```

### medium-31 `packages/agent/src/earendil_works/pi_agent/agent_loop.py:103-106`

Catching `BaseException` here swallows `asyncio.CancelledError` (and even `KeyboardInterrupt`/`SystemExit`) instead of allowing the producer task's cancellation/system termination to propagate. A cancelled agent task is therefore reported as a normally completed task whose stream merely raises later, which can break task lifecycle/cancellation handling. Handle cancellation separately (wake stream, then re-raise) and catch only the ordinary exceptions expected from the agent loop.

```python
except asyncio.CancelledError as error:
            _end_stream_with_error(stream, error)
            raise
        except Exception as error:
            _end_stream_with_error(stream, error)
        else:
            stream.end(messages)
```

### medium-32 `packages/agent/src/earendil_works/pi_agent/agent_loop.py:135-140`

The continuation path has the same cancellation bug: catching `BaseException` consumes `asyncio.CancelledError` (and system-exit exceptions), so cancellation of this producer task does not propagate to its caller. Wake the stream but re-raise cancellation, and restrict the ordinary failure handler to `Exception`.

```python
try:
            messages = await run_agent_loop_continue(context, config, stream.push, signal, stream_fn)
        except asyncio.CancelledError as error:
            _end_stream_with_error(stream, error)
            raise
        except Exception as error:
            _end_stream_with_error(stream, error)
        else:
            stream.end(messages)
```

### medium-33 `frontend/src/hooks/useTaskStream.ts:68-71`

Polling is only scheduled from `onError`. An EventSource can stay open without delivering task events (for example, a stalled proxy/connection), and this API also emits a heartbeat every 15 seconds, so no error is guaranteed while the task state is stale. Add a watchdog/last-event timeout (or an independent polling safety timer) so the UI cannot remain indefinitely at the state set by `reset` when the stream is silently stalled.

### medium-34 `packages/agent/src/earendil_works/pi_agent/package_manager/collect.py:107-108`

This changes the matching semantics for symlinked files: `target.name` is the resolved destination name, whereas the package-tree entry name (`name`) is what was previously matched. Thus a valid in-boundary link such as `README.md -> docs/readme.txt` (or `prompt.md -> source.txt`) is omitted when the resource pattern matches the link name. Resolve the target for boundary/type checks and returned path, but apply `file_pattern` to `name` to preserve package entry semantics.

```python
elif is_file and file_pattern.search(name):
                files.append(str(target))
```

### medium-35 `packages/ai/src/earendil_works/pi_ai/api/azure_openai_responses_lazy.py:10-10`

This changes the public API from an eagerly initialized stream implementation to `lazy_stream`, but `lazy_stream` only defers setup through its patched `__aiter__`; when the stream is created without a running event loop, it stores the runner in `_pending_setup`, while `EventStream.result()` starts only `_pending_runner`. Thus a caller can create `api["stream"](...)` synchronously and later await `stream.result()` in an event loop, leaving the result future unresolved forever. Either make the lazy stream's `result()`/`await_result()` start `_pending_setup`, or retain eager initialization for this API until that lifecycle path is fixed.

```python
# Use lazy_api only after lazy_stream also starts deferred setup from result()/await_result().
    return lazy_api(load)
```

### medium-36 `packages/ai/src/earendil_works/pi_ai/api/_http_stream.py:224-228`

This validation stops at `choice`; `choice.get("delta")` can still yield a truthy non-dict, and `delta.get("tool_calls")` can contain non-dict entries (with `tc.get`) or a non-dict `function` value (with `fn.get`). A malformed provider frame will therefore raise `AttributeError`/`TypeError` in the background runner instead of producing the intended structured SSE error event. Validate `delta`, each tool-call item, and `function` (or reject the frame) before dereferencing them.

### medium-37 `packages/agent/src/earendil_works/pi_agent/harness/session/jsonl_storage.py:87-89`

`json.loads` accepts `NaN`, `Infinity`, and `-Infinity` by default, and this predicate consequently marks them as safe. Such values are outside JSON and are later emitted by the session writer / API's permissive `json.dumps` as non-standard tokens; browser consumers using `JSON.parse` cannot parse the resulting session/API payload. Reject non-finite floats here (for example with `math.isfinite`) or parse JSON with a `parse_constant` rejection hook.

### medium-38 `packages/ai/src/earendil_works/pi_ai/api/google_shared.py:71-73`

Gemini's `thoughtSignature` is a field on the Part, alongside `functionCall`, not a member of the `functionCall` object. As written, the serialized request uses `functionCall: {name, args, thoughtSignature}`, which does not match the Gemini schema and can cause signed tool-call turns to be rejected or lose the signature required for replay. Add the signature to the part dictionary instead.

```python
part: dict[str, Any] = {"functionCall": call}
                    if block.get("thoughtSignature"):
                        part["thoughtSignature"] = block["thoughtSignature"]
                    parts.append(part)
```

### medium-39 `scripts/_run_one_group.py:135-137`

This block is indented inside the `except` for the SOCM load, so six-stage evidence is collected only when the preceding SOCM processing raises. On a six-stage run where `SocmStore.load()` happens to succeed (or returns an object without error), `collect_evidence.json` and the evidence summary fields are never produced. Move this `try` block out of the SOCM exception handler, and gate it explicitly on the six-stage mode if appropriate.

### medium-40 `packages/ai/src/earendil_works/pi_ai/utils/json_parse.py:39-41`

When the partial JSON ends inside a string whose final character is a comma (for example, `{"value":"a,`), `in_string` is true but this unconditional trimming removes that comma before the string is closed. The repaired JSON then parses successfully with the value changed to `"a"`, silently losing streamed data. Only strip a trailing comma when it is outside a string.

```python
repaired = text
        if not in_string and repaired.endswith(","):
            repaired = repaired[:-1]
```

### medium-41 `packages/ai/src/earendil_works/pi_ai/providers/mistral.py:11-11`

This unconditionally appends `/v1` to every model URL. If a custom/provider-catalog model already supplies a versioned base URL such as `https://api.mistral.ai/v1`, the resulting URL becomes `/v1/v1`; the shared conversations client then appends its endpoint path and requests an invalid endpoint. Normalize only when the URL does not already end in `/v1` (or otherwise centralize this convention).

```python
{**model, "baseUrl": (lambda base: base if base.endswith("/v1") else f"{base}/v1")((model.get("baseUrl") or "https://api.mistral.ai").rstrip("/"))}
```

### medium-42 `packages/ai/src/earendil_works/pi_ai/providers/faux.py:176-178`

This allocation makes `usage["input"]` zero for every non-empty prompt: `cacheWrite` is first set to the entire non-cache-read remainder, then that same remainder is subtracted from `input`. As a result, uncached prompt tokens are reported as cache writes rather than regular input, so consumers that distinguish input and cache-write usage (including cost/observability) receive incorrect classifications. Allocate the uncached remainder to the field intended by the usage contract instead of subtracting the newly assigned `cacheWrite` from it.

### medium-43 `scripts/resume_to_report.py:73-73`

These two writes are individually serialized by the store, but the validation/metadata update/status transition is not atomic. A concurrent `/resume` request can pass its own `task_active` check between these calls and start the runner, and any failure after this metadata write leaves a terminal task with its `stop_after_stage` marker removed while still not pending; rerunning this script then rejects it at the marker check. Please expose a single compare-and-set/transactional resume-preparation operation (or otherwise lock and restore metadata on failure) so the terminal row cannot be partially transitioned.

### medium-44 `packages/ai/src/earendil_works/pi_ai/utils/event_stream.py:47-50`

The task created here is neither retained nor given a completion callback. If `runner()` raises before it calls `push()`/`end()` (including a producer supplied by a caller of the public `start()` method), the task reports an unhandled exception while the result future remains pending forever, so consumers awaiting `await_result()` can hang. Retain the task and propagate its exception to `_result_error`/the result future and wake waiting iterators.

```python
self._started = True
        runner = self._pending_runner
        self._pending_runner = None
        task = loop.create_task(runner())
        task.add_done_callback(self._runner_done)
```

### medium-45 `packages/ai/src/earendil_works/pi_ai/utils/event_stream.py:114-116`

This changes `result()` from a method that could return a Future during synchronous setup to one that unconditionally requires a running event loop. Calling `stream.result()` before entering async code now raises `RuntimeError` (even when no producer is pending), so code that obtains/stores the result future during synchronous construction is broken. Defer only producer startup here, or create/bind the result future using the prior loop-availability behavior.

### medium-46 `tests/competitive_app/unit/sandbox/native/test_sandbox_native_known_issues.py:151-154`

This polling loop has no timeout or failure propagation. If `_ask_network` raises before writing a request (or its protocol changes so `writer.lines` is never populated), the test yields forever and can hang the entire test suite instead of failing. Await the task with a bounded timeout (and clean it up on timeout), or use an event/queue with a timeout.

### medium-47 `tests/capability_packages/pi_auto_review/test_known_issues_capabilities.py:75-76`

This fixture does not actually test that a provider-qualified reference requires a matching model: `right/same` is absent, while `right/other` is present. `resolve_reviewer` then takes its provider fallback and synthesizes an entry with id `same`, so the assertions pass even without an exact provider/model registration. Add `{"provider": "right", "id": "same", ...}` (and use a distinct wrong-provider id) or assert the missing-model behavior expected by the contract.

```python
{"provider": "wrong", "id": "same", "name": "wrong"},
                {"provider": "right", "id": "same", "name": "right"},
```

### medium-48 `tests/competitive_app/unit/test_api_wiring_known_issues.py:60-62`

`start()` creates a long-lived pump task, and the `stage_start` event is not terminal, so `_pump()` remains blocked on `source.get()` after this test finishes. The test also leaves both subscriber queues registered. Add teardown/cleanup (or send a terminal event and await/cancel the pump) so this async test does not leave pending work behind or retain subscribers.

### medium-49 `tests/competitive_app/unit/sandbox/native/test_srt_manager_proxy_known_issues.py:132-135`

Despite the test name, this only proves that the proxy returned 200 and that the filter callback saw `127.0.0.1`; it never proves that the origin accepted a connection or that bytes crossed the tunnel. A proxy that returns success before dialing, dials an incorrect endpoint, or closes the tunnel immediately would still pass. Send a payload after the handshake and assert the echoed response (and/or record an origin-side connection).

### medium-50 `tests/competitive_app/unit/sandbox/native/test_srt_manager_proxy_known_issues.py:65-72`

These tests mutate module-global manager state and only reset it after assertions. If `wrap_with_sandbox`, an assertion, or the filter call raises, `_config` and related lifecycle state remain installed and can contaminate later tests (the parameterized cases also share this risk). Put the mutation and assertions in a `try/finally` or use an autouse fixture that always calls `manager.reset()`.

### medium-51 `tests/competitive_app/unit/test_workflow_runtime_known_issues.py:109-112`

This single event-loop yield does not deterministically prove that the second `prompt` has entered `register_queued`/started waiting on the lock. If `abort_session` runs before that task is scheduled, it cancels no waiter; the second prompt can then wait for the first prompt's `release`, while this test awaits it before setting `release`, causing a hang (or allowing the prompt to proceed instead of raising). Synchronize on an explicit event/state transition from the queued prompt before aborting.

```python
second = asyncio.create_task(service.prompt("s", "second"))
    while not registry._queued.get("s"):
        await asyncio.sleep(0)
    await registry.abort_session("s")
    with pytest.raises(SessionAbortedError):
```

### medium-52 `tests/competitive_app/unit/test_workflow_known_issues.py:108-111`

This assertion cannot exercise the failing sub-agent path: after `state.budget.max_queries = 0`, `_dispatch_parallel` returns before spawning any task when the query dimension is disabled/exhausted. Therefore `failing` is never called and no `search sub-agent failed` record can be emitted, so this test fails regardless of the exception-observation behavior it intends to verify. Run the failure case with a positive remaining budget (or assert the no-dispatch behavior separately).

### medium-53 `tests/scripts/test_misc_scripts.py:15-16`

`load_script` mutates the process-wide environment and never restores the previous values. After either test imports `_run_one_group.py` or `resume_to_report.py`, all `GROUP_*`/`RESUME_*` variables remain set for the rest of the pytest process, so later tests or imports that read these variables can observe this test's paths and IDs, creating order-dependent failures (and parallel-test interference). Snapshot `os.environ` and restore it in a `finally` block, or use `monkeypatch.setenv` in the tests.

### medium-54 `tests/packages/ai/unit/test_ai_core_known_issues.py:55-56`

This test is named as a refresh-race regression test, but both resolution calls are awaited sequentially and the refresh callback is never instrumented with a call count or synchronization barrier. It therefore passes even if concurrent expired requests all refresh independently (or overwrite one another), so it cannot detect the claimed race fix. Run two `_resolve_stored_oauth` calls concurrently against the same store and assert that refresh is coordinated / the resulting credentials are consistent.

### medium-55 `tests/packages/agent/unit/test_harness_known_issues.py:100-101`

This assertion accepts an invalid chronological context: the compaction summary is emitted before the pre-compaction `old` message, even though `old` precedes the compaction entry in the session path. A stale anchor should preserve the original path/order (or otherwise append the summary after retained history); otherwise the model receives history out of order and this regression test masks that defect.

```python
result = default_context_entry_transform(entries)  # type: ignore[arg-type]
    assert [entry["id"] for entry in result] == ["old", "compact"]
```

### medium-56 `tests/packages/ai/unit/test_ai_api_known_issues.py:185-186`

This test does not identify the public factory explicitly: it selects the first callable in `vars(module)` whose name ends with `_api`. A future helper or alias matching that predicate can be selected instead, so the actual provider wrapper could stop delegating to `lazy_api` while this test still passes (or the test could fail for an unrelated helper signature). Call the expected factory by name for each parameterized module.

## Low（22）

### low-1 `competitive_app/src/competitive_app/application/workflow/task_service.py:1007-1010`

This catch preserves the persisted task outcome, but silently discards every evolution-cycle exception. Since `run_cycle()` is the only post-task evolution trigger here, production failures become invisible. Log the exception or emit a non-fatal evolution failure journal/event while continuing to preserve the task status.

### low-2 `competitive_app/src/competitive_app/application/workflow/session_service.py:194-206`

These compensation failures are silently discarded. If shutdown, repository deletion, or index deletion fails, `create_session` still re-raises the original error without any indication that a session file or index row may remain, making partial-create leaks and inconsistent state difficult to diagnose. Log the exception (with the session id/path) while preserving the original exception.

### low-3 `competitive_app/src/competitive_app/application/workflow/runtime_registry.py:177-184`

Cleanup failures are silently discarded, so shutdown can report success while a harness subprocess, lock, or other resource remains leaked. Preserve best-effort cleanup, but log the exception (and preferably identify the session/harness) so operational failures are diagnosable.

### low-4 `frontend/src/pages/TracePage.tsx:44-46`

The rejection is converted to an empty span list without any error state, so a network/API failure is rendered as “无 trace span” and is indistinguishable from a valid report with no spans. This can mislead users and makes recovery difficult; preserve an error flag/message (and optionally a retry action) and render it separately from the empty state.

### low-5 `frontend/src/hooks/useTaskStream.ts:45-47`

When the initial GET fails, this catch suppresses the only diagnostic, while `reset` has already set the task to `running`. If the SSE connection also fails and every polling request fails, the polling catch below is likewise silent, leaving the workspace indefinitely in a loading/running state with no user-visible error. Preserve/report a terminal stream error after the fallback fails (while still ignoring expected AbortError during cleanup).

### low-6 `packages/agent/src/earendil_works/pi_agent/harness/skills.py:49-49`

The opening delimiter is checked without trimming surrounding whitespace, while the closing delimiter accepts it and the previous `startswith("---")` logic also parsed lines such as `---   `. A skill file using `---   ` therefore leaves its front matter in `content` and silently loses `name`, `description`, and `disableModelInvocation`. Normalize the opening delimiter consistently with the closing one (or preserve the prior accepted syntax).

```python
if lines and lines[0].rstrip("\r\n").strip() == "---":
```

### low-7 `packages/agent/src/earendil_works/pi_agent/harness/session/jsonl_storage.py:119-122`

The new validation only checks that each content block is a dict, so arbitrary or incomplete blocks (for example `{}` or `{"type": "toolCall"}` without its required fields) are accepted as `AgentMessage` data. `session_entry_to_context_messages` then exposes them directly and `convert_to_llm` forwards them to provider adapters, where malformed transcripts can be rejected or cause downstream runtime errors. Validate the supported block variants and their required fields (or validate the complete `AgentMessage` shape) before accepting the entry.

### low-8 `scripts/resume_to_report.py:60-60`

The script reaches into two private `TaskService` helpers instead of using the service's public resume operation. This couples an operational/reporting script to implementation details: a refactor can rename or change either underscored method while the public `/resume` contract remains valid, causing this script to fail before it issues the resume request. Please add a public preparation/resume API for this workflow, or move these checks into the existing `resume_task` service path.

### low-9 `tests/competitive_app/unit/evolution/test_eval_known_issues.py:3-3`

`json` is imported but never referenced in this test module (the `json` in the test/function names is not a symbol use). Remove the unused import to keep the test file lint-clean.

### low-10 `tests/capability_packages/pi_auto_review/test_known_issues_capabilities.py:120-124`

The module-level `ContextVar` binding is only cleaned up on the success path. If either assertion (or a future assertion added here) fails after `bind_runtime`, the `

### low-11 `tests/competitive_app/unit/sandbox/native/test_srt_manager_proxy_known_issues.py:166-170`

The new body-limit coverage only exercises an oversized declared length/chunk size. It does not cover a body that reaches the limit cumulatively across multiple chunks, or malformed/truncated chunk framing. Those are the paths where streaming implementations commonly bypass the aggregate limit or silently accept incomplete input; add cases that send several legal chunks whose sum exceeds the limit and cases with invalid/truncated framing.

### low-12 `tests/competitive_app/unit/sandbox/native/test_sandbox_facade_known_issues.py:102-107`

This regression test resolves both `root` and `cwd` from the process working directory, unlike the other capability-loader tests which derive the repository root from `__file__`. Running pytest from an IDE, subdirectory, or another working directory makes `root` point at the wrong location (and strict mode raises before testing registry acceptance). Resolve `capability_packages` relative to the test file/repository root instead.

```python
root = Path(__file__).resolve().parents[4] / "capability_packages"
    report = await load_capability_packages(
        root,
        enabled=["echo_example"],
        cwd=root,
        strict=True,
    )
```

### low-13 `tests/competitive_app/unit/test_domain_known_issues.py:119-120`

This assertion relies on the current insertion order of `Frontier.tasks`, although the preceding assertion only establishes membership. If frontier storage or eviction later reorders tasks, it may inspect the dependency rather than the intended dependent and make this regression test brittle. Select the task by ID before asserting its status.

```python
assert frontier.dequeue() is not None
    dependent = next(task for task in frontier.tasks if task.id == "dependent")
    assert dependent.status == FrontierTaskStatus.BLOCKED
```

### low-14 `tests/competitive_app/unit/test_persistence_observability_known_issues.py:58-60`

The store is closed only after the assertions, so any failed assertion or exception before this line leaves the aiosqlite connection open for the remainder of the test. Wrap the test body in `try/finally` (or add a fixture that yields the store and closes it in teardown) so cleanup is guaranteed on failure; apply the same pattern to the other async store tests in this file.

### low-15 `tests/competitive_app/unit/test_api_wiring_known_issues.py:97-100`

This only checks that the path is registered in OpenAPI; it does not exercise `stream_task` or assert that its return value is a `StreamingResponse`. A regression replacing the handler with a buffered response would still pass, so the test does not cover the streaming behavior claimed by its name. Invoke the route with a lightweight request/state fixture and assert the response type (and ideally the SSE media type).

### low-16 `tests/competitive_app/unit/test_workflow_runtime_known_issues.py:280-281`

This assertion only checks that the mocked status store received no updates. It does not establish that `_run_research` consumed the runner's `"completed"` result or successfully reached post-task evaluation; an early return or unrelated skip would also satisfy it. Assert the expected successful-run behavior (for example, completion status or a post-evaluation invocation) while separately verifying that the evolution exception is isolated.

### low-17 `tests/competitive_app/unit/test_workflow_known_issues.py:128-130`

The `Intake` instance is created inside `build_ephemeral` and is not retained by the test, so `flushed` is never asserted. This test passes even if the cancellation cleanup omits `await intake.flush()`, and thus does not verify the stated regression. Store the returned intake in an outer variable and assert its `flushed` flag after the expected `CancelledError`.

### low-18 `tests/packages/agent/unit/test_agent_core_known_issues.py:118-118`

This assertion is too permissive for the tool that actually ran: `_tool("first")` returns a normal result and only sets `signal.aborted` after entering execution, so its result should be asserted as non-error. As written, a regression that incorrectly marks the executed first call as an error still passes, leaving only the synthesized second result verified.

```python
assert [m["isError"] for m in results] == [False, True]
```

### low-19 `tests/packages/agent/unit/test_agent_core_known_issues.py:78-80`

The single `await asyncio.sleep(0)` does not explicitly synchronize with `_run_with_lifecycle` reaching the active state. If the created task has not yet executed its synchronous setup (`self._active_run = ...` and `isStreaming = True`), `reset()` will run before the intended condition and the `pytest.raises` assertion will fail intermittently (or this test will no longer exercise the active-run guard after lifecycle scheduling changes). Use a synchronization event/callback from the executor after startup, or await a state-specific readiness signal, before mutating the state and calling `reset()`.

### low-20 `tests/packages/ai/unit/test_ai_core_known_issues.py:214-218`

The assertion only checks the final event's type. A regression that drops the assistant message, emits an error before `done`, or produces an invalid event sequence would still pass. Since this test is intended to cover starting a faux stream after synchronous construction, also assert the collected events include the expected assistant payload and completion semantics.

### low-21 `tests/packages/ai/unit/test_ai_core_known_issues.py:196-198`

The stream coverage exercises only successful completion and `end()` without a result. It does not verify producer exceptions, cancellation, or cross-loop push/consumption behavior, which are precisely the fragile lifecycle paths introduced by deferred startup and loop-independent result storage. Add at least an exception/cancellation case and a producer/consumer loop-boundary case so failures cannot leave awaiters hanging or lose events.

### low-22 `tests/packages/agent/unit/test_harness_known_issues.py:21-21`

`build_session_context` is imported but never referenced in this test module. With the repository's unused-import checks this can fail linting; remove it (or use it in a test).

```python
from earendil_works.pi_agent.harness.session import InMemorySessionRepo
```

---

> 生成时间：2026-08-04T10:30:47

## 第二轮修复状态（2026-08-04）

> 本轮 89 条 finding 均已完成代码或回归测试修复；对应 focused verification 随 issue slice 执行，最终回归结果由本分支验证记录补充。

### High（11/11）

- [x] high-1 — capability module trusted-root validation
- [x] high-2 — broker IPC drain
- [x] high-3 — Linux policy deny-write compatibility
- [x] high-4 — descriptor-relative manifest staging
- [x] high-5 — ripgrep cancellation cleanup
- [x] high-6 — workspace descriptor handoff and TOCTOU rejection
- [x] high-7 — negative/malformed Content-Length rejection
- [x] high-8 — evolution rollback recovery error
- [x] high-9 — atomic skill projection publication
- [x] high-10 — frontier superset target merge
- [x] high-11 — explicit native allow-read configuration

### Medium（56/56）

- [x] medium-1 — medium-3 — complete redaction before bounding
- [x] medium-2 — non-blocking SOCM cross-process lock
- [x] medium-4 — medium-6 — SSE fanout/subscriber lifecycle and snapshot errors
- [x] medium-7 — registry import failure fail-closed
- [x] medium-8 — owner-aware extension runtime teardown
- [x] medium-9 — medium-11 — sandbox approval/protocol input validation
- [x] medium-12 — medium-13 — guarded session/task rollback
- [x] medium-14 — stronger coverage provenance
- [x] medium-15 — medium-16 — atomic query budget and failed-subagent propagation
- [x] medium-17 — repeated-source evidence citation preservation
- [x] medium-18 — cancellation-safe session lock release
- [x] medium-19 — finite wall-budget overflow rejection
- [x] medium-20 — medium-22 — bounded runtime stream lifecycle and abort handling
- [x] medium-23 — composition-wide resource rollback
- [x] medium-24 — medium-30 — frontend rejection, loading, freshness, and error handling
- [x] medium-31 — medium-32 — cancellation propagation in agent loops
- [x] medium-33 — silent EventSource watchdog
- [x] medium-34 — package-entry symlink pattern matching
- [x] medium-35 — deferred lazy stream startup
- [x] medium-36 — nested provider-frame validation
- [x] medium-37 — non-finite JSONL rejection
- [x] medium-38 — Gemini thoughtSignature placement
- [x] medium-39 — six-stage evidence collection path
- [x] medium-40 — string-safe partial JSON repair
- [x] medium-41 — Mistral URL normalization
- [x] medium-42 — faux usage allocation
- [x] medium-43 — atomic public resume preparation
- [x] medium-44 — medium-45 — EventStream runner/result lifecycle
- [x] medium-46 — medium-56 — deterministic regression-test hardening

### Low（22/22）

- [x] low-1 — low-3 — cleanup/evolution diagnostics
- [x] low-4 — low-5 — frontend trace/stream error visibility
- [x] low-6 — whitespace-tolerant skill front matter
- [x] low-7 — JSONL content-block validation
- [x] low-8 — public resume preparation API usage
- [x] low-9 — unused import cleanup
- [x] low-10 — low-12 — context/runtime/SRT fixture cleanup and path grounding
- [x] low-13 — low-17 — deterministic competitive-app regression assertions
- [x] low-18 — low-22 — deterministic agent/AI/harness regression assertions

### 验证记录

- `uv run pytest -q` focused OCR suites：**210 passed**
- `uv run pytest -q -m 'not live'`：**1027 passed / 39 deselected**
- native provider/runner/broker descriptor suites：**55 passed**；macOS real enforcement：**11 passed**
- live research workflow + workflow skill evolution：**9 passed**
- live packages/agent + packages/ai：**14 passed**
- live search capability（不含 Grok）：**6 passed / 2 deselected**
- frontend `npm run build`：**passed**（仅既有 chunk-size warning）
- Python `compileall`、`git diff --check`：**passed**
- Grok live：**2 failed — provider HTTP 503**；同一配置此前通过，当前判定为外部 provider 故障，不回退或吞错。

high-6 采用 workspace/manifest descriptor 全链路传递、broker 最终 fd↔path identity 校验、`fchdir` 与 worker descriptor 读取；当前 SRT Seatbelt/bwrap policy API 本身仍以 path 表达 allowRead/cwd，无法改写为纯 descriptor policy。production broker 路径已 fail-closed；仅测试/legacy custom broker 保留 staged-path compatibility。

## 第三轮 OpenCodeReview（2026-08-04）

- raw：`docs/reviews/2026-08-04_round2_cr.json`
- session：`35ec1563-9f35-4542-82ed-49774a025255`
- 范围：当前工作区 77 files；OCR 结果 **54 comments**（10 high / 33 medium / 11 low）
- 处理：**41 fixed / 13 accepted with rationale**

### 已修复（41）

- manifest fd 显式配置失败时 fail-closed；fake broker fixture 显式保留 fd
- ripgrep timeout/abort/caller-cancel 全路径 kill + wait/reap，并恢复结果解析
- coverage cancellation 清理并 await 全部 pending subagent
- RuntimeRegistry done callback、terminal 去重、session lock timeout race
- credential store typing/import 与 modify/write/delete 互斥
- SOCM flock OSError fail-closed，lock file preparation 移入线程
- native runtime/provider/runner descriptor 与 socketpair 异常路径清理
- task rollback/resume CAS 加 `updated_at`
- `from_manifest` capability target 重新做 trusted-root 校验
- evolution active pointer 缺验证能力时 fail-closed
- skill scope 快照/clear/恢复、rollback 日志、目录 fsync
- frontier superset 合并保留 `blocked_by`
- agent loop 非 `Exception` BaseException 唤醒 stream 后传播
- late EventStream producer error 可见、SSE tool index 拒绝负数
- SSE fanout teardown/subscribe 以锁串行；修复锁内递归死锁
- Dashboard 独立加载、Library 成功重试清错、Report section-local refine error
- 相关弱测试改为真实行为/spy/严格时序，新增 fd/CAS/fanout/frontier/credential 回归

### 保留（13，非缺陷）

- high-3：Linux 使用 concrete deny paths；Darwin glob 仅 Seatbelt，不能在 bwrap 复用。
- high-4：subagent LLM failure 已 exception-log + `help.requested` journal；属于显式降级，不将单子任务 provider failure 扩大为整轮失败。取消泄漏另行修复。
- high-10：`abort_task()` bool 表示 control-plane abort 是否命中；runner cleanup exception 被 await+log，不代表 persisted workflow 成功。
- medium-12：subscriber queue 256 + drop-oldest 是有界 backpressure 策略，避免慢客户端制造无界内存。
- medium-15：trusted-root/import broad catch 返回拒绝是安全边界的 fail-closed 行为。
- medium-29/30/31：异常启动清理继续执行其他 best-effort cleanup；production store 使用 conditional/atomic API，fallback 仅窄 test double/legacy compatibility。
- medium-33：composition 捕获 `BaseException` 仅用于 rollback resources，随后原样 re-raise；取消不会被吞。
- medium-34：HTTP generation 在请求开始时递增实现 last-started-wins；`eventVersion` 阻止 SSE 后的 stale snapshot 覆盖。
- medium-40：`EventStream.result()` 无 running loop 时返回 Awaitable，签名与 docstring 已声明 union。
- low-50：Trace 条件 JSX 为展示风格，无状态或错误语义缺陷。
- low-52：测试读取 provider 私有 fd map 是 ownership/close regression 的有意白盒断言。

### 第三轮验证

- 新增/修正 focused：**121 passed**（53 + 68）
- SRT/native coverage regressions：**32 passed**
- 非 live 全量：**1037 passed / 39 deselected / 2 existing warnings**
- frontend `npm run build`：**passed**（仅既有 >500 kB chunk warning）
- `git diff --check`：**passed**

## 第四轮 OpenCodeReview 修复（2026-08-04）

- raw：`docs/reviews/2026-08-04_round3_cr.json`
- session：`0403cf29-e72f-4a44-81f9-767be07fe07e`
- 范围：commit `3748458`，80 files
- OCR 结果：**28 comments**（3 high / 19 medium / 4 low / 2 unranked）
- 处理：**28 fixed / 0 deferred**

### 修复摘要

- capability module origin 在 import 前以 trusted-root filesystem identity 校验，拒绝 manifest 触发未授权模块副作用
- Linux `preserve_fds` 强制进入 bwrap path，fd 校验移至 active counter 递增之前
- scope store 明确要求 get/set/clear contract；快照成功后才启用 rollback，durable projection write 移入 worker thread
- SOCM prepare/flock/unlock 均在 cancellation 后等待 thread 完成，descriptor 最终关闭
- NativeRuntime close 阻止新 admission、等待 in-flight command；provider release/destroy/shutdown 以 finally 关闭 retained fd
- coverage pool 对任意 BaseException 取消并收割 siblings
- RuntimeRegistry 恢复 `start_task` 返回值；terminal retention 绑定 stream identity，旧 generation 不再删除 live replacement
- task rollback/delete CAS mismatch 显式告警；不完整 session metadata 优先 opaque cleanup
- application composition rollback 捕获 cleanup BaseException，继续释放全部资源且保留原 startup failure
- Dashboard latest-request-wins；dashboard/subscriptions 独立错误；刷新失败保留旧数据；API 层不再吞掉这两类请求错误
- JSONL create/append/leaf write 使用 strict `allow_nan=False`
- EventStream 唤醒 non-Exception BaseException consumers，并在 producer 完成后释放 task/traceback 引用
- credential、resume、stream、fanout 等测试改为 deterministic/public-contract assertions，teardown 显式 unsubscribe/close

### 第四轮验证

- focused OCR regressions：**140 passed**
- 非 live 全量：**1053 passed / 39 deselected / 2 existing warnings**
- frontend `npm run build`：**passed**（仅既有 >500 kB chunk warning）
- browser：初始 dashboard+subscription 成功渲染；subscription 503 保留旧列表且显示 section error；并发刷新最终保留 newer dashboard/subscription 结果
- `npm run lint`：未执行到 lint；仓库使用 ESLint 10 但缺少 `eslint.config.js`（既有工具配置问题）