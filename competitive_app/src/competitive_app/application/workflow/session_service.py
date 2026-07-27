"""Session service — create / prompt / abort / get / messages.

Bridges HTTP layer to earendil_works.pi_agent (AgentHarness + JsonlSessionRepo)
and the SQLite session index. Per-session lock serializes prompts with queue
timeout → 409 (feature F-A10); abort cancels in-flight + queued (F-A11).
"""
from __future__ import annotations

import asyncio
from typing import Any, Protocol

from earendil_works.pi_agent.agent import Agent, AbortController

from ...domain.task import Task  # noqa: F401  (kept for layering clarity; not used yet)
from .runtime_registry import RuntimeRegistry


class ModelResolver(Protocol):
    """Resolves a request ``model`` string to a pi_ai Model dict.

    Empty string → default model; unknown id → raises KeyError (→ 422).
    """

    def resolve(self, model: str) -> dict[str, Any]: ...


class HarnessFactory(Protocol):
    """Builds an AgentHarness bound to a given session + model + system prompt.

    ``model=None`` means "use the configured default" (research-workflow-v1 F-R7).
    """

    async def build(
        self,
        *,
        session: Any,
        model: dict[str, Any] | None,
        system_prompt: str,
    ) -> Any: ...


class SessionConflictError(Exception):
    """Raised when a prompt cannot acquire the session lock in time (→ 409)."""


class SessionAbortedError(Exception):
    """Raised when a queued prompt was cancelled by abort (→ 409)."""


class SessionNotFoundError(Exception):
    """Raised when a session_id is not in the index (→ 404)."""


class ModelResolutionError(Exception):
    """Raised when a requested model is not in the catalog (→ 422)."""


class SessionService:
    def __init__(
        self,
        *,
        repo: Any,
        store: Any,
        registry: RuntimeRegistry,
        harness_factory: HarnessFactory,
        model_resolver: ModelResolver,
        prompt_lock_timeout: float = 30.0,
    ) -> None:
        self._repo = repo
        self._store = store
        self._registry = registry
        self._harness_factory = harness_factory
        self._model_resolver = model_resolver
        self._prompt_lock_timeout = prompt_lock_timeout

    async def create_session(
        self,
        *,
        model: str,
        system_prompt: str,
        metadata: dict[str, Any],
        cwd: str,
    ) -> dict[str, Any]:
        resolved_model = self._resolve_model(model)
        session = await self._repo.create({"cwd": cwd})
        meta = await session.get_metadata()
        harness = await self._harness_factory.build(
            session=session, model=resolved_model, system_prompt=system_prompt
        )
        self._registry.register_harness(meta["id"], harness)
        await self._store.index_session(
            session_id=meta["id"],
            file_path=meta["path"],
            cwd=cwd,
            model=model,
            system_prompt=system_prompt,
        )
        return {
            "session_id": meta["id"],
            "status": "idle",
            "model": model or _model_name(resolved_model),
            "metadata": metadata,
        }

    async def get_session(self, session_id: str) -> dict[str, Any]:
        record = await self._store.get_session(session_id)
        if record is None:
            raise SessionNotFoundError(session_id)
        return {
            "session_id": record["session_id"],
            "model": record["model"],
            "system_prompt": record["system_prompt"],
            "created_at": record["created_at"],
        }

    async def prompt(self, session_id: str, content: Any) -> dict[str, Any]:
        record = await self._store.get_session(session_id)
        if record is None:
            raise SessionNotFoundError(session_id)
        harness = self._registry.get_harness(session_id)
        if harness is None:
            # Resume path: rebuild harness from the indexed config.
            session = await self._repo.open(
                {"path": record["file_path"], "cwd": record["cwd"]}
            )
            resolved_model = self._resolve_model(record["model"])
            harness = await self._harness_factory.build(
                session=session,
                model=resolved_model,
                system_prompt=record["system_prompt"],
            )
            harness = self._registry.register_harness(session_id, harness)
        agent = harness.agent
        lock = self._registry.lock_for(session_id)
        try:
            await asyncio.wait_for(lock.acquire(), timeout=self._prompt_lock_timeout)
        except asyncio.TimeoutError as exc:
            raise SessionConflictError(
                f"session {session_id} is busy; prompt queue timeout"
            ) from exc
        try:
            await harness.prompt(content)
        finally:
            lock.release()

        return {
            "session_id": session_id,
            "message": _last_assistant_message(agent),
            "status": "idle",
        }

    async def abort(self, session_id: str) -> dict[str, Any]:
        await self._registry.abort_session(session_id)
        return {"session_id": session_id, "status": "aborted"}

    async def messages(self, session_id: str) -> dict[str, Any]:
        record = await self._store.get_session(session_id)
        if record is None:
            raise SessionNotFoundError(session_id)
        session = await self._repo.open(
            {"path": record["file_path"], "cwd": record["cwd"]}
        )
        context = await session.build_context()
        return {"session_id": session_id, "messages": list(context["messages"])}

    def _resolve_model(self, model: str) -> dict[str, Any]:
        try:
            return self._model_resolver.resolve(model)
        except KeyError as exc:
            raise ModelResolutionError(str(exc)) from exc


def _last_assistant_message(agent: Agent) -> dict[str, Any] | None:
    for message in reversed(agent.state.messages):
        if isinstance(message, dict) and message.get("role") == "assistant":
            return message
    return None


def _model_name(model: dict[str, Any]) -> str:
    return str(model.get("id") or model.get("name") or "")


__all__ = [
    "HarnessFactory",
    "ModelResolutionError",
    "ModelResolver",
    "SessionAbortedError",
    "SessionConflictError",
    "SessionNotFoundError",
    "SessionService",
]
