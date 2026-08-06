"""Task service — create / list / get / resume / abort / delete (three-stage runner).

research-workflow-v1 v0.2.0: the runner is ResearchRunner, which runs the three
stages (plan/search/write) against a real pi_agent AgentHarness. The search
stage delegates to CoverageEngine (ADR 0010 D-S8) which drives the iterative
coverage-map search loop and persists SOCM. Stage outputs go to JSONL; task
status/progress + coverage projection go to SQLite.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from ...adapter.out.observability import guarded_append
from ...adapter.out.observability.run_journal import RunJournal
from ...domain.research_brief import ResearchBrief
from ...domain.stage import STAGES, empty_projection
from .journal_bridge import current_run_journal
from .research_runner import ResearchRunner
from .runtime_registry import RuntimeRegistry
_log = logging.getLogger(__name__)

class TaskNotFoundError(Exception):
    """Raised when a task_id is not in the store (→ 404)."""


class TaskConflictError(Exception):
    """Raised when a task is already running (→ 409)."""


class TaskInputError(Exception):
    """Raised when task creation input is invalid (→ 422)."""


class TaskService:
    def __init__(
        self,
        *,
        store: Any,
        repo: Any,
        registry: RuntimeRegistry,
        harness_factory: Any,
        capability_tools: list[Any] | None = None,
        sessions_cwd: str = "competitive_app",
        socm_store: Any = None,
        judge_model: dict[str, Any] | None = None,
        models: Any = None,
        skill_snapshot: Any = None,
        skill_composer: Any = None,
        skill_store: Any = None,
        skill_judgment_analyzer: Any = None,
        task_quality_judge: Any = None,
        evolution_cycle_runner: Any = None,
        post_task_observer: Any = None,
        sandbox_lifecycle: Any | None = None,
        llm_configured: bool = False,
        runs_root: str = "data/runs",
    ) -> None:
        self._store = store
        self._repo = repo
        self._registry = registry
        self._harness_factory = harness_factory
        self._capability_tools = list(capability_tools or [])
        self._sessions_cwd = sessions_cwd
        self._socm_store = socm_store
        self._judge_model = judge_model
        self._models = models
        self._skill_snapshot = skill_snapshot
        self._skill_composer = skill_composer
        self._skill_store = skill_store
        self._skill_judgment_analyzer = skill_judgment_analyzer
        self._task_quality_judge = task_quality_judge
        self._post_task_observer = post_task_observer
        self._evolution_cycle_runner = evolution_cycle_runner
        self._sandbox_lifecycle = sandbox_lifecycle
        self._llm_configured = llm_configured
        self._runs_root = Path(runs_root)
        self._journals: dict[str, RunJournal] = {}
        self._runners: dict[str, tuple[ResearchRunner, asyncio.Event, Any]] = {}

    async def ping_llm(self) -> dict[str, Any]:
        """GET /api/v2/llm/ping — real LLM round-trip diagnostic (batch4 v0.3.4).

        One ``completeSimple`` call with a trivial prompt. Returns
        ``{ok, model, reply, latency_ms}`` on success; ``{ok: False, reason, message}``
        on not-configured or call error. Does NOT pass ``response_format`` — the
        reply is freeform text, not a JSON object (B-path scope is discover/derive).
        Mirrors the discover call shape (single user message, proven to work).
        """
        if not self._llm_configured:
            return {
                "ok": False,
                "reason": "not_configured",
                "message": "LLM not configured (OPENAI_API_KEY/OPENAI_BASE_URL unset and not faux)",
            }
        if self._models is None or self._judge_model is None:
            return {
                "ok": False,
                "reason": "not_configured",
                "message": "models or judge_model not initialized",
            }
        context = {
            "messages": [{"role": "user", "content": "Reply with a single word only, then stop."}]
        }
        t0 = time.monotonic()
        try:
            message = await self._models.completeSimple(self._judge_model, context)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": "error", "message": f"{type(exc).__name__}: {exc}"}
        latency_ms = int((time.monotonic() - t0) * 1000)
        text = _extract_assistant_text_for_refine(message).strip()
        model_name = str(self._judge_model.get("id") or self._judge_model.get("name") or "")
        if not text:
            return {
                "ok": False,
                "reason": "error",
                "message": "empty model reply",
                "model": model_name,
                "latency_ms": latency_ms,
            }
        return {"ok": True, "model": model_name, "reply": text[:200], "latency_ms": latency_ms}

    async def create_task(
        self,
        *,
        research_brief: ResearchBrief | None = None,
        query: str | None = None,
        metadata: dict[str, Any] | None = None,
        skip_clarify: bool = False,
        search_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /tasks — create a research task.

        v0.3.3: overloaded. Caller supplies exactly one of:
          - ``research_brief``: structured brief → run immediately (legacy path).
          - ``query``: free-form query → clarify flow (awaiting_clarify) unless
            ``skip_clarify`` (subscription run path: derive brief, run directly).
        v0.3.5: optional ``search_overrides`` (per-task search hyperparameters).
          Clamped + persisted in metadata["search_overrides"] for resume (F-R16).
        """
        metadata = dict(metadata or {})
        if search_overrides:
            metadata["search_overrides"] = _clamp_search_overrides(search_overrides)
        if research_brief is not None and query is not None:
            raise TaskInputError("provide exactly one of research_brief or query")
        if research_brief is None and not (query and query.strip()):
            raise TaskInputError("provide research_brief or query")

        # Legacy / structured path — byte-identical to pre-v0.3.3 behavior.
        if research_brief is not None:
            return await self._start_research_task(research_brief, metadata)

        # Query path.
        query = (query or "").strip()
        if skip_clarify:
            # Subscription run: derive brief from query directly (no human Q&A).
            discovered = await self._safe_discover(query)
            brief = await self._derive_brief(query, [], discovered, [])
            return await self._start_research_task(brief, metadata)

        # Clarify path: discover scope + ask 2-4 questions.
        result = await self._safe_discover_with_questions(query)
        if result is None:
            # Q3-A degrade: discovery failed entirely → skip clarify, run directly.
            discovered = {"subject": query, "domain": "", "competitors": []}
            brief = await self._derive_brief(query, [], discovered, [])
            return await self._start_research_task(brief, metadata)
        # Awaiting clarify — create the task row WITHOUT a session (deferred to
        # submit_clarify so an abandoned query leaves no orphan session, F-R14).
        task_id = uuid.uuid4().hex
        clarify = {
            "query": query,
            "status": "awaiting",
            "discovered": {
                "subject": result["subject"],
                "domain": result["domain"],
                "competitors": result["competitors"],
            },
            "questions": result["questions"],
        }
        metadata["clarify"] = clarify
        await self._store.create_task(
            task_id=task_id,
            query=query[:120],
            status="awaiting_clarify",
            metadata=metadata,
            projection=empty_projection(),
            session_id=None,
        )
        return {
            "task_id": task_id,
            "session_id": None,
            "status": "awaiting_clarify",
            "query": query[:120],
            "questions": result["questions"],
        }

    async def submit_clarify(self, task_id: str, answers: list[dict[str, Any]]) -> dict[str, Any]:
        """POST /tasks/{task_id}/clarify — derive brief from answers + start research.

        Resolves an ``awaiting_clarify`` task: reads the stored query/questions/
        discovered scope, derives a ResearchBrief via a 2nd LLM call, creates the
        session (F-R14 1:1, deferred to this moment), and starts the runner.
        """
        task = await self._store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        if task["status"] != "awaiting_clarify":
            raise TaskConflictError(f"task {task_id} is not awaiting clarify")
        metadata = task.get("metadata") or {}
        clarify = metadata.get("clarify") or {}
        query = clarify.get("query") or task.get("query") or ""
        discovered = clarify.get("discovered") or {
            "subject": query,
            "domain": "",
            "competitors": [],
        }
        questions = clarify.get("questions") or []
        brief = await self._derive_brief(query, questions, discovered, answers)
        # Record answers + derived brief into metadata, then start research.
        metadata.setdefault("clarify", {})
        metadata["clarify"]["answers"] = answers
        metadata["clarify"]["brief"] = brief.model_dump(mode="json")
        metadata["clarify"]["status"] = "resolved"
        await self._store.update_task_metadata(task_id, metadata)
        return await self._start_research_task(brief, metadata, task_id=task_id)

    async def _start_research_task(
        self,
        research_brief: ResearchBrief,
        metadata: dict[str, Any],
        *,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Create the session + task row + kick off the runner (F-R14/F-R22).

        Shared by the research_brief path, the skip_clarify (subscription) path,
        and submit_clarify. F-R14 (1:1 task↔session) holds at the moment research
        actually starts.
        """
        task_id = task_id or uuid.uuid4().hex
        query = _display_title(research_brief)
        # Capture an existing clarify row before creating any session so a
        # failed transition can restore it without leaving a pending orphan.
        existing = await self._store.get_task(task_id)
        session = await self._repo.create({"cwd": self._sessions_cwd})
        meta: dict[str, Any] | None = None
        session_id = ""
        operation: Any | None = None
        stream_registered = False
        task_touched = False
        try:
            meta = await session.get_metadata()
            session_id = meta["id"]
            await self._store.index_session(
                session_id=session_id,
                file_path=meta["path"],
                cwd=self._sessions_cwd,
                model="",  # default model (F-R7); resolved inside harness
                system_prompt="",
            )
            stop_after_stage = _metadata_stop_after(metadata)
            task_touched = True
            if existing is None:
                await self._store.create_task(
                    task_id=task_id,
                    query=query,
                    status="pending",
                    metadata=metadata,
                    projection=empty_projection(),
                    session_id=session_id,
                )
            else:
                await self._store.update_task_status(
                    task_id, "pending", projection=empty_projection(), session_id=session_id
                )
                await self._store.update_task_metadata(task_id, metadata)
            self._registry.register_stream(task_id)
            stream_registered = True
            operation = self._run_research(
                task_id, research_brief, session, session_id, stop_after_stage=stop_after_stage
            )
            self._registry.start_task(task_id, self, operation)
        except BaseException:
            if operation is not None:
                operation.close()
            if stream_registered:
                self._registry.unregister_stream(task_id)
            if task_touched:
                await self._rollback_task_row(task_id, existing, session_id=session_id)
            cleanup_meta = meta or await self._metadata_for_cleanup(session)
            await self._cleanup_created_session(cleanup_meta, session=session)
            raise
        return {
            "task_id": task_id,
            "session_id": session_id,
            "status": "pending",
            "query": query,
        }

    async def _rollback_task_row(
        self, task_id: str, existing: dict[str, Any] | None, *, session_id: str = ""
    ) -> None:
        """Conditionally undo this startup transition without delete/recreate gaps."""
        restore = getattr(self._store, "restore_task_if_current", None)
        delete = getattr(self._store, "delete_task_if_current", None)
        if existing is not None and restore is not None:
            try:
                restored = await restore(
                    existing, expected_status="pending", expected_session_id=session_id
                )
                if not restored:
                    _log.warning("conditional task rollback skipped after concurrent change: %s", task_id)
                return
            except Exception:
                _log.exception("conditional task rollback failed for %s", task_id)
                return
        if existing is None and delete is not None:
            try:
                deleted = await delete(
                    task_id, expected_status="pending", expected_session_id=session_id
                )
                if not deleted:
                    _log.warning("conditional task delete skipped after concurrent change: %s", task_id)
                return
            except Exception:
                _log.exception("conditional task delete failed for %s", task_id)
                return
        # Compatibility for narrow test doubles that predate the conditional API.
        try:
            await self._store.delete_task(task_id)
            if existing is not None:
                await self._store.create_task(
                    task_id=task_id,
                    query=existing.get("query", ""),
                    status=existing["status"],
                    metadata=existing.get("metadata") or {},
                    projection=existing.get("projection") or empty_projection(),
                    session_id=existing.get("session_id"),
                )
        except Exception:
            _log.exception("task rollback failed for %s", task_id)

    async def _metadata_for_cleanup(self, session: Any) -> dict[str, Any] | None:
        """Recover metadata after an initial metadata read failed, if possible."""
        candidates = [getattr(session, "metadata", None), getattr(session, "_metadata", None)]
        try:
            storage = session.get_storage()
            if hasattr(storage, "__await__"):
                storage = await storage
            candidates.extend([getattr(storage, "_metadata", None), {"path": getattr(storage, "_file_path", "")}])
        except Exception:
            pass
        partial: dict[str, Any] | None = None
        for value in candidates:
            if not isinstance(value, dict) or not value.get("path"):
                continue
            if value.get("id"):
                return value
            partial = value
        try:
            value = await session.get_metadata()
            if isinstance(value, dict) and value.get("path") and value.get("id"):
                return value
        except Exception:
            _log.exception("unable to recover complete metadata for created session cleanup")
        return partial
    async def _cleanup_created_session(
        self, meta: dict[str, Any] | None, *, session: Any = None
    ) -> None:
        """Remove JSONL, index, and eagerly-created workspace on rollback."""
        if meta is not None and not meta.get("id") and session is not None:
            try:
                await self._repo.delete(session)
                return
            except Exception:
                _log.exception("opaque created session cleanup failed; using path fallback")
        if not meta:
            if session is not None:
                try:
                    await self._repo.delete(session)
                    return
                except Exception:
                    _log.exception("opaque created session cleanup failed")
            _log.error("created session cleanup skipped: metadata unavailable")
            return
        session_id = meta.get("id")
        if self._sandbox_lifecycle is not None and session_id:
            try:
                await self._sandbox_lifecycle.delete_workspace(session_id=session_id)
            except Exception:
                _log.exception("workspace cleanup failed for session %s", session_id)
        try:
            await self._repo.delete({"path": meta["path"], "cwd": self._sessions_cwd})
        except Exception:
            _log.exception("JSONL cleanup failed for session %s", session_id)
        if self._socm_store is not None and session_id:
            try:
                await self._socm_store.delete(session_id)
            except Exception:
                _log.exception("SOCM cleanup failed for session %s", session_id)
        if session_id:
            try:
                await self._store.delete_session(session_id)
            except Exception:
                _log.exception("session index cleanup failed for session %s", session_id)

    async def list_tasks(self) -> dict[str, Any]:
        tasks = await self._store.list_tasks()
        return {"tasks": tasks}

    async def get_task(self, task_id: str) -> dict[str, Any]:
        task = await self._store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task

    async def prepare_resume_task(self, task_id: str) -> dict[str, Any]:
        """Validate and atomically prepare a stopped task for resume.

        This is the public preparation path used by offline resume tooling; the
        runner-starting ``resume_task`` endpoint remains responsible for launch.
        """
        task = await self._store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        status = task.get("status")
        if status not in {"completed", "failed", "aborted"}:
            raise TaskConflictError(f"task {task_id} is not resumable from status {status!r}")
        if self._first_non_ok_stage(task.get("projection")) is None:
            raise TaskConflictError(f"task {task_id} has no incomplete stage to resume")
        if self._registry.task_active(task_id):
            raise TaskConflictError(f"task {task_id} is already running")
        session_id = task.get("session_id")
        if not session_id:
            raise TaskConflictError(f"task {task_id} has no session to resume")
        metadata = dict(task.get("metadata") or {})
        if not metadata.get("stop_after_stage"):
            raise TaskConflictError(f"task {task_id} has no stop_after_stage marker")
        if await self._load_research_brief(session_id) is None:
            raise TaskConflictError(f"task {task_id} brief not recoverable")
        metadata.pop("stop_after_stage", None)
        prepare = getattr(self._store, "prepare_resume_if_current", None)
        if prepare is not None:
            changed = await prepare(
                task_id,
                expected_status=status,
                metadata=metadata,
                expected_updated_at=task.get("updated_at"),
            )
        else:
            await self._store.update_task_metadata(task_id, metadata)
            changed = await self._store.update_task_status(task_id, "pending")
        if not changed:
            raise TaskConflictError(f"task {task_id} changed while preparing resume")
        return {"task_id": task_id, "status": "pending"}

    async def resume_task(self, task_id: str) -> dict[str, Any]:
        task = await self._store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        if task["status"] == "completed":
            return {"task_id": task_id, "status": "completed"}
        if self._registry.task_active(task_id):
            raise TaskConflictError(f"task {task_id} is already running")
        # Validate every recovery prerequisite while the terminal status is
        # still intact; failures must not leave an unstarted task as pending.
        start_stage = self._first_non_ok_stage(task.get("projection"))
        session_id = task.get("session_id")
        if not session_id:
            # No session means the task was aborted before clarify was submitted
            # (F-R14: session deferred to clarify). Flip back to awaiting_clarify
            # so the user can re-submit the questionnaire — resume is not for
            # re-running stages (there are none to re-run).
            meta = task.get("metadata") or {}
            clarify = meta.get("clarify") if isinstance(meta, dict) else None
            if isinstance(clarify, dict) and clarify.get("status") == "awaiting":
                await self._store.update_task_status(task_id, "awaiting_clarify")
                return {"task_id": task_id, "status": "awaiting_clarify"}
            raise TaskConflictError(f"task {task_id} has no session to resume")
        research_brief = await self._load_research_brief(session_id)
        if research_brief is None:
            raise TaskConflictError(f"task {task_id} brief not recoverable")
        session = await self._open_session(session_id)

        original_status = task["status"]
        operation: Any | None = None
        stream_registered = False
        try:
            await self._store.update_task_status(task_id, "pending")
            self._registry.register_stream(task_id)  # pre-register buffered stream
            stream_registered = True
            operation = self._run_research(
                task_id, research_brief, session, session_id, start_stage=start_stage
            )
            self._registry.start_task(task_id, self, operation)
        except BaseException:
            if operation is not None:
                operation.close()
            if stream_registered:
                self._registry.unregister_stream(task_id)
            try:
                await self._store.update_task_status(task_id, original_status)
            except Exception:
                pass
            raise
        return {"task_id": task_id, "status": "pending"}

    async def abort_task(self, task_id: str) -> dict[str, Any]:
        task = await self._store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        # F-R21: signal the runner + cancel the asyncio.Task + agent.abort.
        entry = self._runners.get(task_id)
        if entry is not None:
            _runner, abort_signal, agent = entry
            abort_signal.set()
            if agent is not None:
                agent.abort()
        await self._registry.abort_task(task_id, "api_abort")
        # E4: task abort rejects new scope calls and destroys the whole
        # container; the workspace is preserved.
        session_id = task.get("session_id") or ""
        if self._sandbox_lifecycle is not None and session_id:
            await self._sandbox_lifecycle.destroy(session_id=session_id)
        # Only flip to aborted if not already terminal.
        if task["status"] not in {"completed", "failed", "aborted"}:
            await self._store.update_task_status(task_id, "aborted")
        return {"task_id": task_id, "status": "aborted"}

    async def delete_task(self, task_id: str) -> None:
        task = await self._store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        if self._registry.task_active(task_id):
            await self._registry.abort_task(task_id, "delete")
        session_id = await self._store.delete_task(task_id)
        if self._skill_store is not None:
            try:
                await self._skill_store.delete_task_references(task_id)
            except Exception:
                pass
        if session_id:
            # E4: abort/destroy first, then delete only the derived workspace
            # as part of the session/JSONL/SOCM/index cascade.
            if self._sandbox_lifecycle is not None:
                await self._sandbox_lifecycle.delete_workspace(session_id=session_id)
            await self._cascade_delete_session(session_id)
        # B4: task 删除级联删 run 目录（data/runs/<task_id>）。
        shutil.rmtree(self._runs_root / task_id, ignore_errors=True)
        self._journals.pop(task_id, None)
        self._runners.pop(task_id, None)

    async def get_report(self, task_id: str) -> dict[str, Any]:
        task = await self._store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        # F-R12: return write stage output.
        report = None
        stage = None
        session_id = task.get("session_id")
        if session_id:
            session = await self._open_session(session_id)
            from .stage_outputs import get_stage_output

            write_out = await get_stage_output(session, "write")
            if write_out is not None:
                report = write_out.get("report")
                stage = "write"
        return {
            "task_id": task_id,
            "status": task["status"],
            "stage": stage,
            "report": report,
        }

    # ------------------------------------------------------- v0.3.1 reports

    async def list_reports(self) -> dict[str, Any]:
        """GET /reports — completed-task cards (newest first).

        Cards read purely from SQLite projection (no file IO). Card fields
        (report_title/brands/evidence_count/claim_count) are populated by the
        runner on task completion.
        """
        tasks = await self._store.list_completed_reports()
        return {"reports": [self._task_to_report_card(t) for t in tasks]}

    async def get_report_full(self, task_id: str) -> dict[str, Any]:
        """GET /reports/{task_id} — structured full report (real-time assembly).

        Reads write markdown from JSONL + coverage/sources from SOCM. No extra
        storage, no stale (always reads the search SoT). Returns not-ready when
        the task isn't completed or has no write output.
        """
        task = await self._store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        proj = task.get("projection") or {}
        # Not ready: task not completed, or no write output yet.
        if task["status"] != "completed" or not proj.get("report_title"):
            return {
                "ok": False,
                "message": "report not ready",
                "report_id": task_id,
                "status": task["status"],
            }
        session_id = task.get("session_id")
        markdown = ""
        sections: list[dict[str, Any]] = []
        if session_id:
            session = await self._open_session(session_id)
            from .stage_outputs import get_stage_output

            # v0.3.2: prefer refine stage_output (post-refine) over write (original).
            out = await get_stage_output(session, "refine") or await get_stage_output(
                session, "write"
            )
            out = out or {}
            markdown = out.get("report") or ""
            sections = out.get("sections") or []
        # Coverage four-state + sources from SOCM.
        coverage = {"filled": 0, "total": 0, "unknown": 0, "conflict": 0, "ratio": 0.0}
        sources: list[str] = []
        coverage_map: dict[str, Any] | None = None
        if session_id and self._socm_store is not None:
            socm = await self._socm_store.load(session_id)
            coverage = socm.coverage_map.to_projection_with_states()
            sources = sorted({n.source for n in socm.evidence_graph.nodes if n.source})
            # F2: coverage_map matrix for GraphPage (read-only projection; D-S4).
            try:
                coverage_map = socm.coverage_map.to_matrix()
            except Exception:  # noqa: BLE001
                coverage_map = None
        result = {
            "ok": True,
            "report_id": task_id,
            "title": proj.get("report_title") or task.get("query", ""),
            "markdown": markdown,
            "sections": sections,
            "coverage": coverage,
            "evidence_count": proj.get("evidence_count", 0),
            "sources": sources,
            "created_at": task.get("created_at", ""),
        }
        if coverage_map is not None:
            result["coverage_map"] = coverage_map
        return result

    # --------------------------------------------------- v0.3.2 trace/refine/feedback

    async def get_trace(self, task_id: str) -> dict[str, Any]:
        """GET /tasks/{task_id}/trace — call-level spans (token/latency)."""
        task = await self._store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        spans = await self._store.list_spans(task_id)
        return {"task_id": task_id, "spans": spans}

    async def refine_report(
        self, task_id: str, section_id: str, annotations: list[str]
    ) -> dict[str, Any]:
        """POST /reports/{task_id}/refine — rewrite one section via LLM.

        Reads the current report (refine > write), locates the section by id,
        rewrites its body with SOCM evidence + annotations via completeSimple,
        then appends a "refine" stage_output (D24 append-only; write preserved).
        """
        from .research_runner import _split_sections
        from .stage_outputs import append_stage_output, get_stage_output

        task = await self._store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        session_id = task.get("session_id")
        if not session_id:
            return {"ok": False, "message": "no session", "report_id": task_id}
        session = await self._open_session(session_id)
        # 1. read current report (refine > write) + sections
        out = await get_stage_output(session, "refine") or await get_stage_output(session, "write")
        out = out or {}
        report = out.get("report") or ""
        sections = out.get("sections") or _split_sections(report)
        # 2. locate section
        target = next((s for s in sections if str(s.get("id")) == str(section_id)), None)
        if target is None:
            return {"ok": False, "message": "section not found", "report_id": task_id}
        # 3. filter SOCM evidence by section title keywords + top-N
        evidence = await self._filter_evidence_for_section(session_id, target.get("title", ""))
        # 4. LLM rewrite body
        new_body = await self._rewrite_section(target, evidence, annotations)
        if not new_body:
            return {"ok": False, "message": "rewrite failed", "report_id": task_id}
        # 5. splice back into report + sections
        new_report = _replace_section_body(report, sections, str(section_id), new_body)
        new_sections = [
            {**s, "body": new_body, "refined": True} if str(s.get("id")) == str(section_id) else s
            for s in sections
        ]
        # 6. append refine stage_output (D24: append, don't overwrite write)
        await append_stage_output(
            session,
            "refine",
            {
                "section_id": section_id,
                "report": new_report,
                "sections": new_sections,
                "refined_at": _now_iso(),
            },
        )
        await self._run_refinement_observation(task_id, section_id, annotations)
        return {"ok": True, "section_id": section_id, "report_id": task_id}

    async def add_feedback(
        self, task_id: str, edited_blocks: int, total_blocks: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        """POST /reports/{task_id}/feedback — record revision rate."""
        task = await self._store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        await self._store.save_feedback(task_id, edited_blocks, total_blocks, data)
        rate = (edited_blocks / total_blocks) if total_blocks else 0.0
        return {"ok": True, "report_id": task_id, "revision_rate": round(rate, 4)}

    # ----------------------------------------------------- v0.3.3 clarify (LLM)

    async def _safe_discover(self, query: str) -> dict[str, Any]:
        """Discover scope (subject/domain/competitors) only; tolerate failure."""
        result = await self._safe_discover_with_questions(query)
        if result is None:
            return {"subject": query, "domain": "", "competitors": []}
        return {
            "subject": result["subject"],
            "domain": result["domain"],
            "competitors": result["competitors"],
        }

    async def _safe_discover_with_questions(self, query: str) -> dict[str, Any] | None:
        """One LLM call: discover scope, then assemble 3 hardcoded questions.

        Returns None on total failure (LLM unavailable) → caller degrades to
        skip-clarify (Q3-A). On success returns {subject, domain, competitors,
        questions}. competitors-empty still yields focus+market questions (Q7).
        """
        if self._models is None or self._judge_model is None:
            return None
        # English + single-user-message prompt (mirrors the judge prompt style that
        # produces clean JSON from the reasoning main model; Chinese system+user
        # prompts made the model emit prose instead of JSON).
        prompt = (
            "You are a competitive-intelligence research director doing pre-research scope "
            "discovery. Given a one-line user research request, identify: (1) the true research "
            "subject (product/company/category full name); (2) its sub-domain/sector; (3) as many "
            "real direct competitors as possible (8-12, must be real searchable products/companies, "
            "ordered by popularity descending, do NOT include the subject itself).\n\n"
            "IMPORTANT: If the user's request explicitly lists multiple products/companies to "
            "compare (e.g. 'X、Y、Z 对比' / 'X vs Y vs Z' / 'X and Y' / '为 X、Y、Z 做 SWOT'), "
            "those listed products MUST be included in competitors — they are the comparison "
            "targets the user wants researched. subject = the shared category/sector they belong "
            "to (e.g. '企业协作平台'), NOT the product list itself.\n\n"
            f"User request: {query}\n\n"
            'Return ONLY a JSON object: {"subject": "<subject>", "domain": "<domain>", '
            '"competitors": ["<comp1>", "<comp2>", ...]}. '
            "Output ONLY the JSON object, no explanation, no markdown."
        )
        context = {"messages": [{"role": "user", "content": prompt}]}
        try:
            message = await self._models.completeSimple(
                self._judge_model,
                context,
                options={"response_format": {"type": "json_object"}},
            )
        except Exception:  # noqa: BLE001
            return None
        if message is None:
            return None
        text = _extract_assistant_text_for_refine(message)
        parsed = _try_parse_json(text)
        if not isinstance(parsed, dict) or not (parsed.get("subject") or parsed.get("competitors")):
            return None
        subject = str(parsed.get("subject") or query).strip()
        domain = str(parsed.get("domain") or "").strip()
        comps = [
            str(c).strip()
            for c in (parsed.get("competitors") or [])
            if str(c).strip() and str(c).strip() != subject
        ]
        seen: set[str] = set()
        comps = [c for c in comps if not (c.lower() in seen or seen.add(c.lower()))][:12]
        questions = _build_clarify_questions(subject, comps)
        return {"subject": subject, "domain": domain, "competitors": comps, "questions": questions}

    async def _derive_brief(
        self,
        query: str,
        questions: list[dict[str, Any]],
        discovered: dict[str, Any],
        answers: list[dict[str, Any]],
    ) -> ResearchBrief:
        """2nd LLM call: derive a ResearchBrief from query + scope + answers.

        Hard-constrains competitors>=1 (Q4). Falls back to a minimal brief on
        any failure (LLM unavailable / bad JSON) so the task never stalls.
        """
        subject = discovered.get("subject") or query
        domain = discovered.get("domain") or ""
        discovered_comps = discovered.get("competitors") or []
        answers_blob = _format_clarify_answers(questions, answers)
        # v0.2.8: user-selected competitors (from clarify "competitors" question).
        user_brands: list[str] = []
        by_id = {a.get("id"): a.get("value") for a in answers if isinstance(a, dict)}
        cval = by_id.get("competitors")
        if isinstance(cval, list):
            user_brands = [str(b).strip() for b in cval if str(b).strip()]
        elif isinstance(cval, str) and cval.strip():
            user_brands = [cval.strip()]
        # fallback_brands: user-selected, else regex-extracted from query (VerdaAI port).
        fallback_brands = user_brands or _regex_brands(query)
        if self._models is not None and self._judge_model is not None:
            prompt = (
                "You are a competitive-intelligence research director. Derive a structured "
                "ResearchBrief from the user's original request, the auto-discovered research "
                "subject/domain/candidate competitors, and the user's answers to a clarify "
                "questionnaire.\n"
                "Rules: target.name = the discovered subject; competitors MUST have at least 1 "
                "(use the user's selected ones if any, else pick 1-3 from the candidates by "
                "popularity, else recommend mainstream rivals for the domain); dimensions = the "
                'user\'s selected dimensions, else default to ["功能对比", "定价策略"]; goal = expand '
                "into one clear research objective sentence.\n"
                "IMPORTANT: If the user's request explicitly lists multiple products/companies to "
                "compare (e.g. 'X、Y、Z 对比' / 'X vs Y' / '为 X、Y、Z 做 SWOT'), those listed "
                "products are the comparison targets and MUST be in competitors.\n\n"
                f"Original request: {query}\n"
                f"Subject: {subject}\n"
                f"Domain: {domain}\n"
                f"Candidate competitors: {', '.join(discovered_comps) or '(none)'}\n"
                f"Must-include competitors (user-selected or query-listed): "
                f"{', '.join(fallback_brands) or '(none)'}\n"
                f"User answers:\n{answers_blob or '(none)'}\n\n"
                'Return ONLY a JSON object: {"target": {"name": "", "category": ""}, '
                '"goal": "", "competitors": [""], "dimensions": [""]}. '
                "Output ONLY the JSON object, no explanation, no markdown."
            )
            context = {"messages": [{"role": "user", "content": prompt}]}
            try:
                message = await self._models.completeSimple(
                    self._judge_model,
                    context,
                    options={"response_format": {"type": "json_object"}},
                )
                text = _extract_assistant_text_for_refine(message)
                parsed = _try_parse_json(text)
                if isinstance(parsed, dict):
                    brief = ResearchBrief.model_validate(
                        {
                            "target": {
                                "name": str((parsed.get("target") or {}).get("name") or subject)[
                                    :120
                                ],
                                "category": str(
                                    (parsed.get("target") or {}).get("category") or domain
                                ),
                            },
                            "goal": str(parsed.get("goal") or query),
                            "competitors": _coerce_competitors(
                                parsed.get("competitors"), discovered_comps, fallback_brands
                            ),
                            "dimensions": _coerce_dimensions(parsed.get("dimensions")),
                        }
                    )
                    return brief
            except Exception:  # noqa: BLE001
                pass  # fall through to minimal brief
        # Fallback minimal brief (Q3-A / Q4): never stall the task.
        return ResearchBrief(
            target={"name": subject[:120], "category": domain},
            goal=query,
            competitors=_coerce_competitors(None, discovered_comps, fallback_brands) or ["(待补充)"],
            dimensions=["功能对比", "定价策略"],
        )

    # ----------------------------------------------- v0.3.3 evidence lib + dashboard

    async def list_evidences(
        self,
        *,
        brand: str | None = None,
        source_type: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 200,
    ) -> dict[str, Any]:
        """GET /evidences — global evidence library (cross-task, from projection)."""
        items = await self._store.query_evidences(
            brand=brand,
            source_type=source_type,
            min_confidence=min_confidence,
            limit=limit,
        )
        facets = await self._store.evidence_facets()
        return {"items": items, "facets": facets}

    async def get_dashboard(self) -> dict[str, Any]:
        """GET /dashboard — global aggregation (pure SQL, no SOCM reads)."""
        return await self._store.dashboard_stats()

    # ------------------------------------------------- v0.3.3 subscriptions

    async def create_subscription(
        self, query: str, brands: list[str], interval_hours: int
    ) -> dict[str, Any]:
        sub_id = f"sub_{uuid.uuid4().hex[:8]}"
        return await self._store.create_subscription(sub_id, query, brands, interval_hours)

    async def list_subscriptions(self) -> dict[str, Any]:
        return {"subscriptions": await self._store.list_subscriptions()}

    async def delete_subscription(self, sub_id: str) -> dict[str, Any]:
        ok = await self._store.delete_subscription(sub_id)
        if not ok:
            raise TaskNotFoundError(sub_id)
        return {"ok": True, "sub_id": sub_id}

    async def run_subscription(self, sub_id: str) -> dict[str, Any]:
        """POST /subscriptions/{sub_id}/run — trigger a re-run (no scheduler).

        Derives a brief from the stored query without clarify (skip_clarify=True),
        starts the research, and records the run. Async: returns the task_id
        immediately; caller polls /tasks/{id}/stream or /tasks/{id}.
        """
        import asyncio

        sub = await self._store.get_subscription(sub_id)
        if sub is None:
            raise TaskNotFoundError(sub_id)
        # create_task is async and starts the runner via the registry; await it
        # so the task row exists before we mark the subscription run.
        result = await self.create_task(
            query=sub["query"],
            metadata={"subscription_id": sub_id, "brands": sub.get("brands", [])},
            skip_clarify=True,
        )
        task_id = result["task_id"]
        await self._store.mark_subscription_run(sub_id, task_id)
        # Yield control so the just-started background runner can proceed.
        await asyncio.sleep(0)
        return {"ok": True, "sub_id": sub_id, "task_id": task_id, "status": "pending"}

    async def _filter_evidence_for_section(
        self, session_id: str, title: str
    ) -> list[dict[str, Any]]:
        """Filter SOCM evidence by section-title keyword relevance (top-N)."""
        if self._socm_store is None or not session_id:
            return []
        try:
            socm = await self._socm_store.load(session_id)
        except Exception:  # noqa: BLE001
            return []
        # section title keywords (split on / 、 space; lowercase).
        keywords = {
            w for w in title.lower().replace("/", " ").replace("、", " ").split() if len(w) >= 2
        }
        nodes = list(socm.evidence_graph.nodes)
        if not nodes:
            return []

        def _relevance(node: Any) -> int:
            blob = f"{node.entity} {node.attribute} {node.value} {node.finding or ''}".lower()
            return sum(1 for kw in keywords if kw in blob)

        ranked = sorted(nodes, key=_relevance, reverse=True)
        # keep only relevant (relevance > 0) when keywords exist; else top by confidence.
        if keywords:
            ranked = [n for n in ranked if _relevance(n) > 0] or ranked
        return [
            {
                "entity": n.entity,
                "attribute": n.attribute,
                "value": n.value,
                "source": n.source,
                "confidence": n.confidence,
            }
            for n in ranked[:30]
        ]

    async def _rewrite_section(
        self, section: dict[str, Any], evidence: list[dict[str, Any]], annotations: list[str]
    ) -> str:
        """LLM rewrite of one section body via completeSimple (judge-style call)."""
        if self._models is None or self._judge_model is None:
            return ""
        title = section.get("title", "")
        existing = section.get("body", "")
        evidence_blob = (
            "\n".join(f"- [{e.get('source', '')}] {e.get('value', '')}" for e in evidence[:30])
            or "(no additional evidence)"
        )
        notes = "\n".join(f"- {a}" for a in annotations if a) or "(no annotations)"
        prompt = (
            "你是资深竞品分析师。用户对报告某章节提出了批注，请基于章节现有内容、可用证据与批注，"
            "把该章节重写得更深、更有针对性——补充论证、数据与对比。输出重写后的章节 markdown "
            "（以 `## ` 标题行开头，到本章节结束，不要包含其他章节）。只输出 markdown 正文。\n\n"
            f"章节标题：{title}\n现有内容：\n{existing}\n\n用户批注：\n{notes}\n\n可用证据：\n{evidence_blob}"
        )
        context = {"messages": [{"role": "user", "content": prompt}]}
        try:
            message = await self._models.completeSimple(self._judge_model, context)
        except Exception:  # noqa: BLE001
            return ""
        text = _extract_assistant_text_for_refine(message)
        return text.strip()

    @staticmethod
    def _task_to_report_card(task: dict[str, Any]) -> dict[str, Any]:
        """Project a completed-task row to a GET /reports card (lightweight)."""
        proj = task.get("projection") or {}
        coverage = proj.get("coverage") or {}
        return {
            "report_id": task["task_id"],
            "title": proj.get("report_title") or task.get("query", ""),
            "brands": proj.get("brands", []),
            "evidence_count": proj.get("evidence_count", 0),
            "claim_count": proj.get("claim_count", 0),
            "coverage_ratio": coverage.get("ratio", 0),
            "status": task["status"],
            "created_at": task.get("created_at", ""),
        }

    async def get_task_sessions(self, task_id: str) -> dict[str, Any]:
        task = await self._store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        # F-R14: 1:1 — return the single associated session.
        session_id = task.get("session_id")
        sessions: list[dict[str, Any]] = []
        if session_id:
            record = await self._store.get_session(session_id)
            if record is not None:
                sessions.append(
                    {
                        "session_id": record["session_id"],
                        "created_at": record["created_at"],
                        "model": record["model"],
                        "status": task["status"],
                    }
                )
        return {"task_id": task_id, "sessions": sessions}

    # ------------------------------------------------------------- runner glue

    def _journal_for(self, task_id: str) -> RunJournal:
        """Run-level journal（B4：run_id = task_id，`data/runs/<task_id>/events.jsonl`）。"""
        journal = self._journals.get(task_id)
        if journal is None:
            journal = RunJournal(task_id, self._runs_root / task_id / "events.jsonl")
            self._journals[task_id] = journal
        return journal

    def _journal_append(self, task_id: str) -> Any:
        """Journal-only append closure（直连 append 点：help.*/skill.*/budget/report.generated）。"""

        def append(event_type: str, payload: dict[str, Any] | None = None) -> None:
            guarded_append(self._journal_for(task_id), event_type, payload)

        return append

    def _make_emit(self, task_id: str) -> Any:
        """v0.3.1 SSE + v0.2.2 trace + 本 feature journal：build the emit closure for a task's runner.

        - `span` events → SQLite (task_spans) + journal (`trace.span`)。NOT pushed
          to SSE (trace is post-hoc; SSE keeps its 11 business events)。
        - 11 业务事件 → journal（`task.<type>`）+ SSE queue（对象原样复用，
          消费者零感知）。
        """

        async def emit(event_type: str, data: dict[str, Any]) -> None:
            if event_type == "span":
                try:
                    await self._store.record_span(task_id, data)
                except Exception:  # noqa: BLE001
                    pass  # span recording must never break the runner
                guarded_append(self._journal_for(task_id), "trace.span", data)
                return
            guarded_append(self._journal_for(task_id), f"task.{event_type}", data)
            self._registry.publish_stream(task_id, {"type": event_type, "data": data})

        return emit

    async def _run_research(
        self,
        task_id: str,
        research_brief: ResearchBrief,
        session: Any,
        session_id: str,
        *,
        start_stage: str | None = None,
        stop_after_stage: str | None = None,
    ) -> None:
        # B4: run 级 journal —— 入口创建（run_id = task_id），run 结束 reset
        # ContextVar（JournalBridge / FallbackStream 经它解析当前 run）。
        journal = self._journal_for(task_id)
        journal_token = current_run_journal.set(journal)
        # Build a per-task harness (F-R7: default model via factory).
        # Always create a fresh harness — resume must not reuse prior runtime state.
        agent: Any = None
        try:
            self._registry.drop_harness(session_id)
            harness = await self._harness_factory.build(
                session=session,
                model=None,  # factory resolves default
                system_prompt="",
            )
            harness = self._registry.register_harness(session_id, harness)
            agent = harness.agent
            abort_signal = asyncio.Event()
            # v0.3.5: read per-task search_overrides from metadata (resume-consistent, F-R16).
            task = await self._store.get_task(task_id)
            task_meta = task.get("metadata") or {} if task else {}
            search_overrides = task_meta.get("search_overrides") if isinstance(task_meta, dict) else None
            runner = ResearchRunner(
                task_id=task_id,
                harness=harness,
                store=self._store,
                socm_store=self._socm_store,
                research_brief=research_brief,
                all_tools=self._capability_tools,
                abort_signal=abort_signal,
                session=session,
                session_id=session_id,
                subagent_factory=self._harness_factory,
                judge_model=self._judge_model,
                emit_event=self._make_emit(task_id),
                journal_append=self._journal_append(task_id),
                skill_snapshot=self._skill_snapshot,
                skill_composer=self._skill_composer,
                search_overrides=search_overrides,
            )
            self._runners[task_id] = (runner, abort_signal, agent)
            result_status = await runner.run(
                start_stage=start_stage, stop_after_stage=stop_after_stage
            )
            await self._post_task_eval(task_id, result_status, runner)
            if self._evolution_cycle_runner is not None and result_status in {
                "completed",
                "failed",
            }:
                # Evolution is observational post-task work: a broken manager or
                # ratchet must never rewrite the already-persisted run outcome.
                try:
                    await self._evolution_cycle_runner.run_cycle()
                except Exception:  # noqa: BLE001
                    _log.exception("post-task evolution cycle failed for %s", task_id)
        except asyncio.CancelledError:
            if agent is not None:
                agent.abort()
            await self._store.update_task_status(task_id, "aborted")
            raise
        except Exception:  # noqa: BLE001
            await self._store.update_task_status(task_id, "failed")
        finally:
            current_run_journal.reset(journal_token)
            self._runners.pop(task_id, None)

    async def _run_refinement_observation(
        self, task_id: str, section_id: str, annotations: list[str]
    ) -> None:
        """Turn a successful feedback-driven refine into an evidence-gated capture.

        The refine operation is the demonstrated solution; feedback is the
        concrete problem evidence. Only a successful completed task is eligible,
        and all exceptions remain observational so reporting never fails.
        """
        if self._post_task_observer is None or not annotations:
            return
        try:
            task = await self._store.get_task(task_id)
            if task is None or task.get("status") != "completed":
                return
            feedback = await self._store.get_feedback(task_id)
            if not feedback:
                return
            note = " ".join(str(item).strip() for item in annotations if str(item).strip())[:240]
            if not note:
                return
            context = await self._post_task_observer.observe(
                task_id=task_id,
                status="completed",
                scope="write",
                problem_signature=f"write.refine.{section_id}: {note}",
                solution=f"Successfully refined write section {section_id} using stored research evidence.",
                transferability="Evidence-grounded write-section refinement is reusable across workflow tasks.",
                evidence_refs=[
                    {"kind": "feedback", "ref": task_id},
                    {"kind": "refine", "ref": f"{task_id}:{section_id}"},
                ],
                suggested_name="write-refinement",
                solution_demonstrated=True,
            )
            if context is not None and self._evolution_cycle_runner is not None:
                record = await self._evolution_cycle_runner.run_context(context)
                if record is not None:
                    await self._post_task_observer.mark_consumed(context.observation_id)
        except Exception:
            return

    async def _post_task_eval(self, task_id: str, status: str, runner: ResearchRunner) -> None:
        if status not in {"completed", "failed"} or self._skill_snapshot is None:
            return
        if self._skill_judgment_analyzer is None and self._task_quality_judge is None:
            return
        try:
            bindings = await self._skill_snapshot.all_bindings(task_id)
            injected = [
                {
                    "skill_id": record.skill_id,
                    "name": record.name,
                    "description": record.description,
                }
                for records in bindings.values()
                for record in records
            ]
            messages = getattr(runner.agent.state, "messages", [])
            summary = json.dumps(messages, ensure_ascii=False, default=str)
            if self._skill_judgment_analyzer is not None and injected:
                await self._skill_judgment_analyzer.analyze_execution(
                    task_id, [], summary, injected, task_completed=status == "completed"
                )
            if self._task_quality_judge is not None:
                await self._task_quality_judge.judge_task(task_id, summary, summary[-20000:])
        except Exception:
            # Post-task metrics are observational and cannot fail the workflow.
            return

    def _first_non_ok_stage(self, projection: Any) -> str | None:
        if not isinstance(projection, dict):
            return None
        stages = projection.get("stages") or {}
        for name in STAGES:
            if stages.get(name) != "ok":
                return name
        return None

    async def _load_research_brief(self, session_id: str) -> ResearchBrief | None:
        """Recover the research brief from the session's first user message."""
        record = await self._store.get_session(session_id)
        if record is None:
            return None
        session = await self._repo.open({"path": record["file_path"], "cwd": record["cwd"]})
        context = await session.build_context()
        for message in context["messages"]:
            if isinstance(message, dict) and message.get("role") == "user":
                content = message.get("content")
                text = _message_text(message)
                # The first user prompt embeds the brief as JSON.
                brief = _extract_brief_from_prompt(text)
                if brief is not None:
                    return brief
        return None

    async def _open_session(self, session_id: str) -> Any:
        """Open a JSONL session by id, translating the store index row to repo metadata."""
        record = await self._store.get_session(session_id)
        if record is None:
            raise TaskConflictError(f"session not indexed: {session_id}")
        return await self._repo.open({"path": record["file_path"], "cwd": record["cwd"]})

    async def _cascade_delete_session(self, session_id: str) -> None:
        record = await self._store.get_session(session_id)
        if record is None:
            return
        # Delete the JSONL session + SOCM search_state.json (F-A17 v0.3.0).
        try:
            await self._repo.delete({"path": record["file_path"], "cwd": record["cwd"]})
        except Exception:
            pass
        if self._socm_store is not None:
            try:
                await self._socm_store.delete(session_id)
            except Exception:
                pass
        await self._store.delete_session(session_id)


def _display_title(research_brief: ResearchBrief) -> str:
    name = (research_brief.target.name or research_brief.target.category).strip()
    if name:
        return name[:120]
    if research_brief.goal.strip():
        return research_brief.goal.strip()[:120]
    return "research task"


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                chunks.append(str(block.get("text") or ""))
        return "".join(chunks)
    return ""


def _extract_brief_from_prompt(text: str) -> ResearchBrief | None:
    import json
    import re

    match = re.search(r"Research brief: (\{.*\})", text)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
        return ResearchBrief.model_validate(data)
    except Exception:
        return None


def _metadata_stop_after(metadata: dict[str, Any]) -> str | None:
    """Read an optional ``stop_after_stage`` from task metadata (experiment harness).

    Validates against STAGES so a bad value can't drive the runner into an
    unknown stage. Returns None when absent/invalid (normal full-pipeline run).
    """
    raw = metadata.get("stop_after_stage") if isinstance(metadata, dict) else None
    if not isinstance(raw, str) or not raw:
        return None
    return raw if raw in STAGES else None


# v0.3.5: per-task search hyperparameter overrides (POST /tasks search_overrides).
# Clamped to safe ranges; type errors → dropped (field omitted, uses env default).
_SEARCH_OVERRIDES_RANGES = {
    "max_parallel": (1, 16, int),
    "coverage_threshold": (0.05, 1.0, float),
    "max_queries": (1, 200, int),
    "max_wall_seconds": (30, 3600, int),
}


def _clamp_search_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    """Clamp + validate search_overrides; drop type-errored fields (Q3).

    Returns only fields with valid values clamped to range. Empty dict if none
    valid → caller treats as "no overrides" (env defaults).
    """
    out: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    for key, (lo, hi, typ) in _SEARCH_OVERRIDES_RANGES.items():
        val = raw.get(key)
        if val is None:
            continue
        try:
            v = typ(val)
        except (TypeError, ValueError):
            continue  # type error → drop field
        if v < lo:
            v = lo
        elif v > hi:
            v = hi
        out[key] = v
    return out


# v0.2.8: query competitor extraction (VerdaAI _regex_brands port). Fallback when
# the user submitted no selected competitors (skip-clarify) — pulls products the
# user explicitly listed in the query ("X、Y、Z" / "X vs Y" / "X 与 Y") so they are
# guaranteed to be searched. Mirrors VerdaAI fallback_brands = user_brands or _regex_brands(query).
_REGEX_BRAND_STOPWORDS = {
    # analysis/report verbs
    "分析", "对比", "竞争", "格局", "调研", "报告", "研究", "评测", "拆解", "梳理",
    # generic nouns
    "产品", "定价", "策略", "市场", "行业", "赛道", "维度", "功能", "口碑", "份额",
    # structural words (SWOT / 4P etc.)
    "结构化", "swot", "4p", "stp", "bcg", "五力", "价值链",
    # particles / fillers
    "的", "与", "和", "为", "做", "一份", "这个", "这些", "及", "以及", "和与",
    # common descriptive tails (not product names)
    "竞争分析", "竞争格局", "市场分析", "产品力", "核心功能",
}
_REGEX_BRAND_MIN_LEN = 2
_REGEX_BRAND_MAX_LEN = 8  # product names are 2-8 chars; longer = descriptive tail
_REGEX_BRAND_LIMIT = 6
# split on Chinese/English separators: 、,，/空格 + "vs"/"对比"/"与"/"和" (word-boundary)
_REGEX_BRAND_SPLIT = re.compile(r"\s*(?:vs|vs\.|对比|与|和|、|,|，|/|，|\s)\s*", re.IGNORECASE)
# leading/trailing filler chars to strip from each token (particles/verbs around the brand)
_REGEX_BRAND_TRIM = "为做把被将让对在从和与及以及"


def _regex_brands(query: str) -> list[str]:
    """Extract product names explicitly listed in a query (v0.2.8 fallback).

    Splits on 、/,/vs/对比/与/和 + trims filler particles + filters
    stopwords/short/numeric tokens. Returns up to 6 candidates.
    """
    if not query:
        return []
    tokens = _REGEX_BRAND_SPLIT.split(query.strip())
    out: list[str] = []
    for t in tokens:
        t = t.strip().strip(_REGEX_BRAND_TRIM).strip()
        # A long token is usually "<brand> <descriptive tail>" (no separator
        # between brand and the rest of the query) — take the leading chunk
        # up to the first space, which is the brand name.
        if len(t) > _REGEX_BRAND_MAX_LEN and " " in t:
            t = t.split(" ", 1)[0].strip(_REGEX_BRAND_TRIM).strip()
        if not t or len(t) < _REGEX_BRAND_MIN_LEN or len(t) > _REGEX_BRAND_MAX_LEN:
            continue
        if t.isdigit():
            continue
        if t.lower() in _REGEX_BRAND_STOPWORDS:
            continue
        if t not in out:
            out.append(t)
    return out[:_REGEX_BRAND_LIMIT]


def _replace_section_body(
    report: str, sections: list[dict[str, Any]], section_id: str, new_body: str
) -> str:
    """v0.3.2: replace one section's body in the full report markdown.

    Splices by locating the target section's current body and substituting
    new_body. Falls back to appending if the body can't be located (defensive).
    """
    target = next((s for s in sections if str(s.get("id")) == str(section_id)), None)
    if target is None or not target.get("body"):
        return report
    old_body = target["body"]
    if old_body and old_body in report:
        return report.replace(old_body, new_body, 1)
    # fallback: append (shouldn't happen if sections were derived from report)
    return report + "\n\n" + new_body


def _extract_assistant_text_for_refine(response: Any) -> str:
    """Pull text from a completeSimple response (mirrors extraction._extract_assistant_text)."""
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        content = response.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    parts.append(str(block.get("text") or block.get("content") or ""))
            return "".join(parts)
        return ""
    if isinstance(response, list):
        for event in reversed(response):
            if not isinstance(event, dict):
                continue
            if event.get("type") in {"message_end", "message"}:
                msg = event.get("message") or event
                content = msg.get("content") if isinstance(msg, dict) else None
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    return "".join(
                        str(b.get("text") or b.get("content") or "")
                        for b in content
                        if isinstance(b, dict)
                    )
            if event.get("type") == "text":
                return str(event.get("text") or "")
        return ""
    return ""


def _now_iso() -> str:
    """v0.3.2: ISO timestamp for refine/feedback records."""
    import datetime

    return datetime.datetime.now(datetime.UTC).isoformat()


# ----------------------------------------------------------- v0.3.3 clarify

_FOCUS_OPTIONS = [
    "功能对比",
    "定价策略",
    "用户口碑",
    "市场份额",
    "技术架构",
    "SWOT",
    "商业模式",
    "舆情趋势",
]
_MARKET_OPTIONS = ["中国大陆", "全球", "北美", "东南亚", "欧洲", "不限"]


def _build_clarify_questions(subject: str, competitors: list[str]) -> list[dict[str, Any]]:
    """Hardcoded 3-question template (Q7), VerdaAI-style {id,question,type,options,hint?}.

    `competitors` is conditional: emitted only when discovery found candidates.
    """
    questions: list[dict[str, Any]] = []
    if competitors:
        questions.append(
            {
                "id": "competitors",
                "question": f"为「{subject}」自动发现了以下候选竞品，请勾选你希望重点对比的对象（可多选）：",
                "type": "multi",
                "options": competitors[:12],
                "hint": "勾选后我们会确保每个竞品都被充分调研；如有遗漏可在下方补充。",
            }
        )
    questions.append(
        {
            "id": "focus",
            "question": "本次调研最看重哪些维度？（可多选）",
            "type": "multi",
            "options": list(_FOCUS_OPTIONS),
        }
    )
    questions.append(
        {
            "id": "market",
            "question": "希望聚焦的目标市场或地区？",
            "type": "single",
            "options": list(_MARKET_OPTIONS),
        }
    )
    return questions


def _format_clarify_answers(questions: list[dict[str, Any]], answers: list[dict[str, Any]]) -> str:
    """Flatten answers (str | list[str]) to a text blob for the derive-brief LLM."""
    by_id = {a.get("id"): a.get("value") for a in answers if isinstance(a, dict)}
    lines: list[str] = []
    for q in questions:
        qid = q.get("id")
        if qid not in by_id:
            continue
        val = by_id[qid]
        if isinstance(val, list):
            val = "、".join(str(v) for v in val if v)
        label = q.get("question", qid).split("（")[0]
        lines.append(f"- {label}：{val}")
    return "\n".join(lines)


def _coerce_competitors(raw: Any, discovered: list[str], must_include: list[str] | None = None) -> list[str]:
    """Ensure competitors is a non-empty list of non-empty strings (Q4).

    v0.2.8: ``must_include`` (query-listed/user-selected brands) are prepended
    if absent — guarantees the user's explicitly-listed products are searched
    even when the LLM omits them. Dedup preserve-order, cap 6.
    """
    must_include = [str(b).strip() for b in (must_include or []) if str(b).strip()]
    comps: list[str] = []
    if isinstance(raw, list):
        comps = [str(c).strip() for c in raw if str(c).strip()]
    # merge: must_include first (user/query intent), then LLM comps, then discovered; dedup
    merged: list[str] = []
    for b in must_include + comps + discovered:
        if b and b not in merged:
            merged.append(b)
    if merged:
        return merged[:6]
    return []


def _coerce_dimensions(raw: Any) -> list[str]:
    if isinstance(raw, list):
        dims = [str(d).strip() for d in raw if str(d).strip()]
        if dims:
            return dims
    return ["功能对比", "定价策略"]


def _try_parse_json(text: str) -> Any:
    """Tolerant JSON parse (re-export shape from research_runner)."""
    from .research_runner import _try_parse_json as _parse

    return _parse(text)


__all__ = ["TaskConflictError", "TaskInputError", "TaskNotFoundError", "TaskService"]
