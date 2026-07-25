"""Wiring — assembles the application state from pi_ai / pi_agent / SQLite.

Contract §6.3 / feature F-A7/F-A9/F-A23. This is the dependency sink:
  - ModelsImpl app-level singleton (stream_fn = models.streamSimple)
  - JsonlSessionRepo (LocalFileSystem(cwd="competitive_app"), data/sessions)
  - TaskProjectionStore (data/app.db)
  - load_capability_packages once at startup; LoadReport cached, applied per harness
  - HarnessFactory + ModelResolver injected into SessionService

Startup failure layering (feature F-A23):
  - Missing provider key does NOT block startup (surfaced at prompt time).
  - Capability package load failure does NOT crash (diagnostics recorded).
  - SQLite / JSONL infra failure raises → lifespan fails fast.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from earendil_works.pi_ai import create_models
from earendil_works.pi_ai.providers.openai import openai_provider

from earendil_works.pi_agent import AgentHarness, JsonlSessionRepo
from earendil_works.pi_agent.harness.env.python_env import LocalFileSystem
from earendil_works.pi_agent.package_manager import load_capability_packages

from .adapter.out.persistence.task_projection_store import TaskProjectionStore
from .application.workflow.runtime_registry import RuntimeRegistry
from .application.workflow.session_service import (
    HarnessFactory,
    ModelResolver,
    SessionService,
)
from .application.workflow.task_service import TaskService


@dataclass
class AppConfig:
    sessions_cwd: str = "competitive_app"
    sessions_root: str = "data/sessions"
    app_db: str = "data/app.db"
    capability_packages_enabled: list[str] = field(default_factory=lambda: ["echo_example"])
    prompt_lock_timeout: float = 30.0
    default_model: str = ""
    # When True, build a faux provider/models for offline tests instead of openai.
    use_faux: bool = False


@dataclass
class ApplicationState:
    config: AppConfig
    models: Any  # ModelsImpl
    repo: JsonlSessionRepo
    store: TaskProjectionStore
    registry: RuntimeRegistry
    session_service: SessionService
    task_service: TaskService
    capability_report: Any | None = None
    capability_diagnostics: list[Any] = field(default_factory=list)

    async def shutdown(self) -> None:
        await self.registry.shutdown()
        await self.store.close()


class _ModelResolver(ModelResolver):
    """Resolves ``model`` string → pi_ai Model dict via the catalog.

    Empty/None → config.default_model; unknown → KeyError (→ 422). Does not allow
    passing a full Model dict (feature F-A8).
    """

    def __init__(self, models: Any, default_model: str) -> None:
        self._models = models
        self._default_model = default_model

    def resolve(self, model: str | None) -> dict[str, Any]:
        model_id = (model or self._default_model) if model is not None else self._default_model
        if not model_id:
            raise KeyError("no model specified and no default configured")
        for candidate in self._models.getModels():
            if candidate.get("id") == model_id:
                return candidate  # type: ignore[return-value]
        raise KeyError(f"model not in catalog: {model_id}")


class _HarnessFactory(HarnessFactory):
    """Builds an AgentHarness bound to a session + model + cached capability report.

    ``model=None`` resolves to the configured default (F-R7).
    """

    def __init__(
        self,
        models: Any,
        capability_report: Any | None,
        model_resolver: _ModelResolver,
    ) -> None:
        self._models = models
        self._capability_report = capability_report
        self._model_resolver = model_resolver

    async def build(
        self,
        *,
        session: Any,
        model: dict[str, Any] | None,
        system_prompt: str,
    ) -> AgentHarness:
        if model is None:
            model = self._model_resolver.resolve(None)
        return AgentHarness(
            session=session,
            stream_fn=self._models.streamSimple,
            model=model,
            system_prompt=system_prompt,
            capability_report=self._capability_report,
        )


async def build_application_state(config: AppConfig) -> ApplicationState:
    """Build the full application state. Called from FastAPI lifespan.

    Raises on infra failure (SQLite/JSONL); does NOT raise on missing provider
    key or capability package failure (feature F-A23).
    """
    # --- models (app-level singleton) --------------------------------------
    models = create_models()
    if config.use_faux:
        from earendil_works.pi_ai.providers.faux import faux_provider

        faux = faux_provider()
        models.setProvider(faux["provider"])  # type: ignore[arg-type]
        # Stash the faux handle so tests can call setResponses via models.__faux.
        models.__faux = faux  # type: ignore[attr-defined]
        # In faux mode, default to the faux model so empty `model` resolves.
        if not config.default_model:
            config.default_model = faux["getModel"]()["id"]
    else:
        provider = openai_provider()
        models.setProvider(provider)

    # --- JSONL repo (infra failure → raise) --------------------------------
    sessions_root = Path(config.sessions_root)
    sessions_root.mkdir(parents=True, exist_ok=True)
    fs = LocalFileSystem(cwd=config.sessions_cwd)
    repo = JsonlSessionRepo({"fs": fs, "sessionsRoot": str(sessions_root)})

    # --- SQLite store (infra failure → raise) ------------------------------
    app_db_path = Path(config.app_db)
    app_db_path.parent.mkdir(parents=True, exist_ok=True)
    store = TaskProjectionStore(str(app_db_path))
    await store.init()

    # --- capability packages (failure → diagnostics, not crash) ------------
    capability_report: Any | None = None
    diagnostics: list[Any] = []
    try:
        capability_report = await load_capability_packages(
            enabled=list(config.capability_packages_enabled)
        )
        diagnostics = list(getattr(capability_report, "diagnostics", []) or [])
    except Exception as exc:  # noqa: BLE001
        diagnostics = [{"level": "error", "message": f"capability load failed: {exc}"}]

    # --- services ----------------------------------------------------------
    registry = RuntimeRegistry()
    model_resolver = _ModelResolver(models, config.default_model)
    harness_factory = _HarnessFactory(models, capability_report, model_resolver)
    session_service = SessionService(
        repo=repo,
        store=store,
        registry=registry,
        harness_factory=harness_factory,
        model_resolver=model_resolver,
        prompt_lock_timeout=config.prompt_lock_timeout,
    )
    capability_tools = list(getattr(capability_report, "tools", []) or []) if capability_report else []
    task_service = TaskService(
        store=store,
        repo=repo,
        registry=registry,
        harness_factory=harness_factory,
        capability_tools=capability_tools,
        sessions_cwd=config.sessions_cwd,
    )

    return ApplicationState(
        config=config,
        models=models,
        repo=repo,
        store=store,
        registry=registry,
        session_service=session_service,
        task_service=task_service,
        capability_report=capability_report,
        capability_diagnostics=diagnostics,
    )


def load_config_from_env() -> AppConfig:
    """Read config from env / settings. Minimal for now (feature §4.5)."""
    enabled = os.environ.get("CAPABILITY_PACKAGES_ENABLED")
    return AppConfig(
        sessions_cwd=os.environ.get("SESSIONS_CWD", "competitive_app"),
        sessions_root=os.environ.get("SESSIONS_ROOT", "data/sessions"),
        app_db=os.environ.get("APP_DB", "data/app.db"),
        capability_packages_enabled=(
            enabled.split(",") if enabled else ["echo_example"]
        ),
        prompt_lock_timeout=float(os.environ.get("PROMPT_LOCK_TIMEOUT", "30")),
        default_model=os.environ.get("OPENAI_MODEL", ""),
        use_faux=os.environ.get("USE_FAUX", "").lower() in ("1", "true", "yes"),
    )


__all__ = ["AppConfig", "ApplicationState", "build_application_state", "load_config_from_env"]
