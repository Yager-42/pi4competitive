"""Task service — create / list / get / resume / abort / delete (three-stage runner).

research-workflow-v1 v0.2.0: the runner is ResearchRunner, which runs the three
stages (plan/search/write) against a real pi_agent AgentHarness. The search
stage delegates to CoverageEngine (ADR 0010 D-S8) which drives the iterative
coverage-map search loop and persists SOCM. Stage outputs go to JSONL; task
status/progress + coverage projection go to SQLite.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from ...domain.research_brief import ResearchBrief
from ...domain.stage import STAGES, empty_projection
from .research_runner import ResearchRunner
from .runtime_registry import RuntimeRegistry


class TaskNotFoundError(Exception):
    """Raised when a task_id is not in the store (→ 404)."""


class TaskConflictError(Exception):
    """Raised when a task is already running (→ 409)."""


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
    ) -> None:
        self._store = store
        self._repo = repo
        self._registry = registry
        self._harness_factory = harness_factory
        self._capability_tools = list(capability_tools or [])
        self._sessions_cwd = sessions_cwd
        self._socm_store = socm_store
        self._judge_model = judge_model
        # v0.3.2 refine: models for completeSimple (section rewrite, like judge).
        self._models = models
        # task_id → (runner, abort_signal, agent) for abort/resume.
        self._runners: dict[str, tuple[ResearchRunner, asyncio.Event, Any]] = {}

    async def create_task(
        self,
        *,
        research_brief: ResearchBrief,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        task_id = uuid.uuid4().hex
        query = _display_title(research_brief)
        # F-R14: create the session immediately (1:1 task↔session).
        session = await self._repo.create({"cwd": self._sessions_cwd})
        meta = await session.get_metadata()
        session_id = meta["id"]
        await self._store.index_session(
            session_id=session_id,
            file_path=meta["path"],
            cwd=self._sessions_cwd,
            model="",  # default model (F-R7); resolved inside harness
            system_prompt="",
        )
        projection = empty_projection()
        await self._store.create_task(
            task_id=task_id,
            query=query,
            status="pending",
            metadata=metadata,
            projection=projection,
            session_id=session_id,
        )
        # Kick off the six-stage runner (F-R22).
        # Experiment harness: optional stop_after_stage from metadata (search-only runs).
        stop_after_stage = _metadata_stop_after(metadata)
        # v0.3.1 SSE: pre-register the event queue before starting the runner so an
        # early SSE connection doesn't miss the first events.
        self._registry.register_stream(task_id)
        self._registry.start_task(
            task_id,
            self,
            self._run_research(
                task_id, research_brief, session, session_id, stop_after_stage=stop_after_stage
            ),
        )
        return {
            "task_id": task_id,
            "session_id": session_id,
            "status": "pending",
            "query": query,
        }

    async def list_tasks(self) -> dict[str, Any]:
        tasks = await self._store.list_tasks()
        return {"tasks": tasks}

    async def get_task(self, task_id: str) -> dict[str, Any]:
        task = await self._store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task

    async def resume_task(self, task_id: str) -> dict[str, Any]:
        task = await self._store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        if task["status"] == "completed":
            return {"task_id": task_id, "status": "completed"}
        if self._registry.task_active(task_id):
            raise TaskConflictError(f"task {task_id} is already running")
        # F-R16: resume from the first non-ok stage.
        start_stage = self._first_non_ok_stage(task.get("projection"))
        # Flip status out of terminal state BEFORE starting the runner, so polling
        # callers don't see the stale failed/aborted status and short-circuit.
        await self._store.update_task_status(task_id, "pending")
        session_id = task.get("session_id")
        if not session_id:
            raise TaskConflictError(f"task {task_id} has no session to resume")
        research_brief = await self._load_research_brief(session_id)
        if research_brief is None:
            raise TaskConflictError(f"task {task_id} brief not recoverable")
        session = await self._open_session(session_id)
        self._registry.register_stream(task_id)  # v0.3.1 SSE: pre-register queue
        self._registry.start_task(
            task_id, self, self._run_research(task_id, research_brief, session, session_id, start_stage=start_stage)
        )
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
        if session_id:
            await self._cascade_delete_session(session_id)
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
            out = await get_stage_output(session, "refine") or await get_stage_output(session, "write")
            out = out or {}
            markdown = out.get("report") or ""
            sections = out.get("sections") or []
        # Coverage four-state + sources from SOCM.
        coverage = {"filled": 0, "total": 0, "unknown": 0, "conflict": 0, "ratio": 0.0}
        sources: list[str] = []
        if session_id and self._socm_store is not None:
            socm = await self._socm_store.load(session_id)
            coverage = socm.coverage_map.to_projection_with_states()
            sources = sorted({n.source for n in socm.evidence_graph.nodes if n.source})
        return {
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
            session, "refine",
            {"section_id": section_id, "report": new_report, "sections": new_sections,
             "refined_at": _now_iso()},
        )
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
            {"entity": n.entity, "attribute": n.attribute, "value": n.value,
             "source": n.source, "confidence": n.confidence}
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
        evidence_blob = "\n".join(
            f"- [{e.get('source', '')}] {e.get('value', '')}" for e in evidence[:30]
        ) or "(no additional evidence)"
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

    def _make_emit(self, task_id: str) -> Any:
        """v0.3.1 SSE + v0.2.2 trace: build the emit closure for a task's runner.

        - `span` events → written to SQLite (task_spans) for GET /tasks/{id}/trace.
          NOT pushed to SSE (trace is post-hoc; SSE keeps its 11 business events).
        - all other events → pushed to the pre-registered SSE queue (if a client
          is connected); no-op when the queue was reaped (task done).
        """

        async def emit(event_type: str, data: dict[str, Any]) -> None:
            if event_type == "span":
                try:
                    await self._store.record_span(task_id, data)
                except Exception:  # noqa: BLE001
                    pass  # span recording must never break the runner
                return
            q = self._registry.get_stream(task_id)
            if q is not None:
                q.put_nowait({"type": event_type, "data": data})

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
            runner = ResearchRunner(
                task_id=task_id,
                harness=harness,
                session=session,
                store=self._store,
                socm_store=self._socm_store,
                research_brief=research_brief,
                all_tools=self._capability_tools,
                abort_signal=abort_signal,
                session_id=session_id,
                subagent_factory=self._harness_factory,
                judge_model=self._judge_model,
                emit_event=self._make_emit(task_id),
            )
            self._runners[task_id] = (runner, abort_signal, agent)
            await self._store.update_task_status(task_id, "running")
            await runner.run(start_stage=start_stage, stop_after_stage=stop_after_stage)
        except asyncio.CancelledError:
            if agent is not None:
                agent.abort()
            await self._store.update_task_status(task_id, "aborted")
            raise
        except Exception:  # noqa: BLE001
            await self._store.update_task_status(task_id, "failed")
        finally:
            self._runners.pop(task_id, None)

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
                        for b in content if isinstance(b, dict)
                    )
            if event.get("type") == "text":
                return str(event.get("text") or "")
        return ""
    return ""


def _now_iso() -> str:
    """v0.3.2: ISO timestamp for refine/feedback records."""
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat()


__all__ = ["TaskConflictError", "TaskNotFoundError", "TaskService"]
