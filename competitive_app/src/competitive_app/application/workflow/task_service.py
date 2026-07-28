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
    ) -> None:
        self._store = store
        self._repo = repo
        self._registry = registry
        self._harness_factory = harness_factory
        self._capability_tools = list(capability_tools or [])
        self._sessions_cwd = sessions_cwd
        self._socm_store = socm_store
        self._judge_model = judge_model
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
        self._registry.start_task(task_id, self, self._run_research(task_id, research_brief, session, session_id))
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

    async def _run_research(
        self,
        task_id: str,
        research_brief: ResearchBrief,
        session: Any,
        session_id: str,
        *,
        start_stage: str | None = None,
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
            )
            self._runners[task_id] = (runner, abort_signal, agent)
            await self._store.update_task_status(task_id, "running")
            await runner.run(start_stage=start_stage)
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


__all__ = ["TaskConflictError", "TaskNotFoundError", "TaskService"]
