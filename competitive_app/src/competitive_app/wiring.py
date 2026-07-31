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

from .adapter.out.persistence.socm_store import SocmStore
from .adapter.out.persistence.learned_skill_store import SQLiteSkillStore
from .adapter.out.persistence.workflow_skill_store import WorkflowSkillStore
from .adapter.out.sandbox.approved_registry import ApprovedToolRegistry
from .adapter.out.sandbox.lifecycle import SandboxLifecycle
from .adapter.out.sandbox.docker.docker_sandbox_provider import DockerSandboxProvider
from .adapter.out.sandbox.docker.local_container_backend import LocalContainerBackend
from .adapter.out.sandbox.docker.local_container_backend import _ALLOWED_ENVIRONMENT
from .adapter.out.sandbox.utils.sandbox_id import derive_sandbox_id
from .adapter.out.sandbox.sandbox_tool_executor import SandboxToolExecutor

from .application.evolution.selector import SkillSelector
from .application.evolution.skill_version_snapshot import SkillVersionSnapshot
from .application.evolution.stage_skill_composer import StageSkillComposer
from .application.evolution.adapters.pi_llm import PiLlmAdapter
from .application.evolution.cycle_runner import EvolutionCycleRunner
from .application.evolution.eval.analyzers.skill_judgment_analyzer import SkillJudgmentAnalyzer
from .application.evolution.eval.analyzers.task_quality_judge import TaskQualityJudge
from .application.evolution.eval.programmatic_bridge import ProgrammaticEvalBridge
from .application.evolution.eval.registry import RegistryEvalBridge, build_default_registry
from .application.evolution.evolution_manager import EvolutionManager
from .application.evolution.focus.ive_focuser import IVEFocuser


from .application.evolution.config import SkillConfig, load_skill_config
from .application.evolution.gates.score_delta_gate import ScoreDeltaGate
from .application.evolution.gates.git_ratchet import GitRatchet
from .application.evolution.post_task_observer import PostTaskObserver
from .application.evolution.skill_files import SkillFiles
from .application.evolution.triggers.metric_monitor import MetricMonitorTrigger
from .adapter.out.persistence.task_projection_store import TaskProjectionStore
from .application.workflow.runtime_registry import RuntimeRegistry
from .application.workflow.session_service import (
    HarnessFactory,
    ModelResolver,
    SessionService,
)
from .application.workflow.task_service import TaskService


@dataclass
class SandboxAppConfig:
    """Production sandbox config: derived image digest + canonical root only.

    E1: exactly two fields — no enabled/provider/tuning switches exist.
    """

    image: str = ""
    root: str = "data/sandboxes"



@dataclass
class AppConfig:
    sessions_cwd: str = "competitive_app"
    sessions_root: str = "data/sessions"
    app_db: str = "data/app.db"
    capability_packages_enabled: list[str] = field(
        default_factory=lambda: [
            "echo_example", "search_tavily", "search_anysearch", "search_grok", "reasonix_prefix_cache"
        ]
    )
    prompt_lock_timeout: float = 30.0
    default_model: str = ""
    use_faux: bool = False
    workflow_skill: SkillConfig = field(default_factory=load_skill_config)
    sandbox: SandboxAppConfig = field(default_factory=SandboxAppConfig)





@dataclass
class ApplicationState:
    config: AppConfig
    models: Any
    repo: JsonlSessionRepo
    store: TaskProjectionStore
    socm_store: SocmStore
    registry: RuntimeRegistry
    session_service: SessionService
    task_service: TaskService
    skill_store: SQLiteSkillStore | None = None
    workflow_skill_store: WorkflowSkillStore | None = None
    skill_selector: SkillSelector | None = None
    skill_snapshot: SkillVersionSnapshot | None = None
    skill_composer: StageSkillComposer | None = None
    skill_files: SkillFiles | None = None
    post_task_observer: PostTaskObserver | None = None
    evolution_manager: EvolutionManager | None = None
    capability_report: Any | None = None
    capability_diagnostics: list[Any] = field(default_factory=list)
    sandbox: SandboxLifecycle | None = None

    async def shutdown(self) -> None:
        await self.registry.shutdown()
        if self.sandbox is not None:
            await self.sandbox.shutdown()
        if self.skill_store is not None:
            await self.skill_store.close()
        if self.workflow_skill_store is not None:
            await self.workflow_skill_store.close()
        await self.store.close()


class _ModelResolver(ModelResolver):
    """Resolves ``model`` string → pi_ai Model dict.

    Empty/None → config.default_model. Resolution order:
      1. explicit ``OPENAI_BASE_URL`` → synthesize a gateway-bound model, even
         when its ID now also exists in the static catalog
      2. static catalog (getModels) — for known models
      3. synthesize an OpenAI-compatible Model for other custom IDs

    No full Model dict accepted from callers (feature F-A8).
    """

    def __init__(self, models: Any, default_model: str, allow_synthesize: bool = False) -> None:
        self._models = models
        self._default_model = default_model
        self._allow_synthesize = allow_synthesize

    def resolve(self, model: str | None) -> dict[str, Any]:
        model_id = (model or self._default_model) if model is not None else self._default_model
        if not model_id:
            raise KeyError("no model specified and no default configured")
        explicit_gateway = self._allow_synthesize and bool(os.environ.get("OPENAI_BASE_URL"))
        if not explicit_gateway:
            for candidate in self._models.getModels():
                if candidate.get("id") == model_id:
                    return candidate  # type: ignore[return-value]
        if not self._allow_synthesize:
            raise KeyError(f"model not in catalog: {model_id}")
        # Explicit gateway or uncatalogued ID: synthesize from env so caller
        # routing is never silently replaced by a catalog provider endpoint.
        base_url = os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        ctx = int(os.environ.get("MODEL_CONTEXT_WINDOW_TOKENS") or "128000")
        return {
            "id": model_id,
            "name": model_id,
            "api": "openai-completions",
            "provider": "openai",
            "baseUrl": base_url,
            "reasoning": False,
            "input": ["text", "image"],
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            "contextWindow": ctx,
            "maxTokens": min(8192, max(1024, ctx // 8)),
        }


class _HarnessFactory(HarnessFactory):
    """Builds an AgentHarness bound to a session + model + cached capability report.

    ``model=None`` resolves to the configured default (F-R7).
    """

    def __init__(
        self,
        models: Any,
        capability_report: Any | None,
        model_resolver: _ModelResolver,
        tool_executor: Any | None = None,
    ) -> None:
        self._models = models
        self._capability_report = capability_report
        self._model_resolver = model_resolver
        self._tool_executor = tool_executor

    def _derive_scope(self, session_id: str) -> str:
        if not session_id:
            return ""
        return derive_sandbox_id(session_id)

    async def build(
        self,
        *,
        session: Any,
        model: dict[str, Any] | None,
        system_prompt: str,
    ) -> AgentHarness:
        if model is None:
            model = self._model_resolver.resolve(None)
        metadata = await session.get_metadata()
        scope_id = self._derive_scope(str(metadata.get("id") or ""))
        return AgentHarness(
            session=session,
            stream_fn=self._models.streamSimple,
            model=model,
            system_prompt=system_prompt,
            capability_report=self._capability_report,
            tool_executor=self._tool_executor,
            tool_execution_scope_id=scope_id,
        )

    async def build_ephemeral(
        self,
        tools: list[Any] | None = None,
        system_prompt: str = "",
        socm_store: Any = None,
        session_id: str = "",
        judge_model: dict[str, Any] | None = None,
        emit_event: Any = None,
        task_id: str = "",
        skills: list[Any] | None = None,
        extraction_skills: list[Any] | None = None,
    ) -> tuple[AgentHarness, Any]:
        """Build an in-memory AgentHarness for an ephemeral sub-agent (F-R28).

        Returns ``(harness, evidence_intake)``. The intake is the PR5
        EvidenceIntake bound to this harness's own extension runtime; the
        coverage engine flushes it at sub-agent exit. Each ephemeral harness
        gets its OWN runtime (fresh ``create_extension_runtime()``) so parallel
        sub-agents never share ``runtime.actions`` or risk cross-invalidation.

        Tools passed directly (NOT via ``capability_report``) — the shared
        ExtensionRuntime is never attached.
        """
        from earendil_works.pi_agent.harness.session.memory_repo import InMemorySessionRepo
        from earendil_works.pi_agent.extensions import (
            attach_extension_runtime,
            create_extension_runtime,
            load_extension_from_factory,
        )
        from earendil_works.pi_agent.extensions.types import LoadExtensionsResult
        from .application.workflow.extraction import EvidenceIntake, make_extraction_extension_factory
        repo = InMemorySessionRepo()
        session = await repo.create({"cwd": "ephemeral"})
        model = self._model_resolver.resolve(None)
        harness = AgentHarness(
            session=session,
            stream_fn=self._models.streamSimple,
            model=model,
            tools=tools or [],
            system_prompt=system_prompt,
            # capability_report=None: shared runtime never attached.
            # The scope derives from the PARENT session id; the in-memory repo
            # id is ignored (E2).
            tool_executor=self._tool_executor,
            tool_execution_scope_id=self._derive_scope(session_id),
        )
        # Attach a per-harness Extraction extension (PR5) if SOCM wiring is provided.
        intake: EvidenceIntake | None = None
        if socm_store is not None and session_id:
            intake = EvidenceIntake(
                socm_store=socm_store,
                session_id=session_id,
                models=self._models,
                judge_model=judge_model,
                emit_event=emit_event,
                task_id=task_id,
                extraction_skills=extraction_skills or [],
            )
            factory = make_extraction_extension_factory(intake)
            runtime = create_extension_runtime()
            extension = await load_extension_from_factory(factory, "ephemeral", runtime, "<extraction>")
            result = LoadExtensionsResult(extensions=[extension], errors=[], runtime=runtime)
            attach_extension_runtime(harness.agent, result, "ephemeral")
        return harness, intake


async def build_application_state(
    config: AppConfig,
    *,
    tool_executor: Any | None = None,
    sandbox_lifecycle: SandboxLifecycle | None = None,
) -> ApplicationState:
    """Build the full application state. Called from FastAPI lifespan.

    Raises on infra failure (SQLite/JSONL); does NOT raise on missing provider
    key or capability package failure (feature F-A23).

    E1/E5: omitted ``tool_executor``/``sandbox_lifecycle`` ALWAYS build the
    production Docker sandbox (image digest + canonical root required, startup
    verification included, failure unwinds before re-raising).  Explicit
    Python-only doubles are accepted for tests; no env/YAML/CLI switch exists
    that disables or replaces the sandbox.
    """
    # --- models (app-level singleton) --------------------------------------
    # E5: doubles must be provided together; validate before any resource opens
    # so a bad composition cannot leak stores.
    if (tool_executor is None) != (sandbox_lifecycle is None):
        raise ValueError("tool_executor and sandbox_lifecycle must be provided together")
    models = create_models()
    if config.use_faux:
        from earendil_works.pi_ai.providers.faux import faux_provider

        faux = faux_provider()
        models.setProvider(faux["provider"])  # type: ignore[arg-type]
        # Stash the faux handle so tests can call setResponses via models.__faux.
        models.__faux = faux  # type: ignore[attr-defined]
        # In faux mode, ALWAYS default to the faux model (ignore .env OPENAI_MODEL
        # so live keys don't leak into offline/faux test runs).
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
    # Workflow Skill operational state shares the existing app.db. These stores
    # bootstrap companion tables even while feature flags are disabled.
    skill_store = SQLiteSkillStore(str(app_db_path))
    await skill_store.init()
    workflow_skill_store = WorkflowSkillStore(str(app_db_path))
    await workflow_skill_store.init()
    skill_selector = SkillSelector(
        skill_store,
        max_skills=config.workflow_skill.max_inject,
        quality_threshold=config.workflow_skill.quality_threshold,
        min_selections=config.workflow_skill.min_selections,
    )
    skill_snapshot = SkillVersionSnapshot(
        selector=skill_selector, skill_store=skill_store, binding_store=workflow_skill_store
    )
    skill_composer = StageSkillComposer()
    skill_files = SkillFiles(config.workflow_skill.root_dir, skill_store, workflow_skill_store)
    post_task_observer = PostTaskObserver(observation_store=workflow_skill_store, skill_store=skill_store)
    evolution_manager = None
    evolution_cycle_runner = None
    judgment_analyzer = None
    quality_judge = None
    if config.workflow_skill.enabled:
        try:
            await skill_store.discover([Path(config.workflow_skill.root_dir) / "skills"])
        except FileNotFoundError:
            pass

    # --- SOCM store (search state of truth, F-R27/D-S4) --------------------
    socm_store = SocmStore(sessions_root)

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

    # --- production sandbox composition (E1) ------------------------------
    # Default/omitted arguments always build Docker.  Explicit Python-only
    # executor + lifecycle doubles are accepted for tests (E5); there is no
    # env/YAML/CLI switch that disables or replaces the sandbox.
    if tool_executor is None:
        if not config.sandbox.image:
            raise ValueError(
                "SANDBOX_IMAGE must be a pinned registry digest; no production fallback exists"
            )
        sandbox_tools = (
            list(getattr(capability_report, "tools", []) or []) if capability_report else []
        )
        sandbox_registry = ApprovedToolRegistry.from_tools(sandbox_tools)
        environment = {name: os.environ.get(name) for name in _ALLOWED_ENVIRONMENT}
        sandbox_root = Path(config.sandbox.root)
        backend = LocalContainerBackend(
            image=config.sandbox.image,
            sandbox_root=sandbox_root,
            environment=environment,
        )
        backend.verify_image_identity()
        provider = DockerSandboxProvider(
            image=config.sandbox.image,
            sandbox_root=sandbox_root,
            environment=environment,
            backend=backend,
        )
        sandbox_executor = SandboxToolExecutor(registry=sandbox_registry, provider=provider)
        lifecycle = SandboxLifecycle(
            provider=provider,
            registry=sandbox_registry,
            executor=sandbox_executor,
            sandbox_root=sandbox_root,
            backend=backend,
        )
        try:
            await provider.start()
            await lifecycle.verify_startup(build_identity=config.sandbox.image)
        except Exception:
            await provider.shutdown()
            # E1.4: unwind already-open App resources (stores) before re-raising.
            await store.close()
            await skill_store.close()
            await workflow_skill_store.close()
            raise
        tool_executor = sandbox_executor
        sandbox_lifecycle = lifecycle

    # --- services ----------------------------------------------------------
    registry = RuntimeRegistry()
    model_resolver = _ModelResolver(models, config.default_model, allow_synthesize=not config.use_faux)
    harness_factory = _HarnessFactory(models, capability_report, model_resolver, tool_executor)
    session_service = SessionService(
        repo=repo,
        store=store,
        registry=registry,
        harness_factory=harness_factory,
        model_resolver=model_resolver,
        prompt_lock_timeout=config.prompt_lock_timeout,
        sandbox_lifecycle=sandbox_lifecycle,
    )
    capability_tools = list(getattr(capability_report, "tools", []) or []) if capability_report else []
    # F-R29: judge model for Extraction. JUDGE_MODEL env if set; else fall back
    # to the main model (judge is a stateless extractor — local F-R7 exemption).
    judge_model_id = os.environ.get("JUDGE_MODEL") or ""
    judge_model: dict[str, Any]
    try:
        judge_model = model_resolver.resolve(judge_model_id) if judge_model_id else model_resolver.resolve(None)
    except KeyError:
        judge_model = model_resolver.resolve(None)
    if config.workflow_skill.enabled and config.workflow_skill.eval_config.enabled:
        try:
            llm_adapter = PiLlmAdapter(models, judge_model)
            judgment_analyzer = SkillJudgmentAnalyzer(llm_adapter, skill_store)
            quality_judge = TaskQualityJudge(llm_adapter, skill_store)
        except Exception:
            judgment_analyzer = None
            quality_judge = None
    if config.workflow_skill.evolve_enabled:
        llm_adapter = PiLlmAdapter(models, judge_model)
        trigger = MetricMonitorTrigger(
            threshold=config.workflow_skill.evolve_threshold,
            min_selections=config.workflow_skill.evolve_min_selections,
            cooldown_turns=config.workflow_skill.evolve_cooldown_turns,
            llm=None,
        )
        from .application.evolution.mutators.llm_mutator import LLMMutator
        focuser = IVEFocuser(llm_adapter)
        mutator = LLMMutator(config.workflow_skill.root_dir,
                             max_changed_lines=config.workflow_skill.evolve_mutate_budget,
                             max_steps=config.workflow_skill.evolve_max_steps,
                             llm=llm_adapter)
        bridge = (RegistryEvalBridge(build_default_registry())
                  if config.workflow_skill.eval_config.enabled else ProgrammaticEvalBridge())
        evolution_manager = EvolutionManager(
            skill_store, [trigger], focuser, mutator, bridge, ScoreDeltaGate(0.0),
            llm=llm_adapter, skill_files=skill_files, scope_store=workflow_skill_store,
        )
        evolution_cycle_runner = EvolutionCycleRunner(
            evolution_manager, GitRatchet(), skill_store, skill_files
        )
    task_service = TaskService(
        store=store,
        repo=repo,
        registry=registry,
        harness_factory=harness_factory,
        capability_tools=capability_tools,
        sessions_cwd=config.sessions_cwd,
        socm_store=socm_store,
        judge_model=judge_model,
        models=models,
        skill_snapshot=skill_snapshot if config.workflow_skill.enabled else None,
        skill_store=skill_store,
        skill_composer=skill_composer,
        skill_judgment_analyzer=judgment_analyzer,
        task_quality_judge=quality_judge,
        post_task_observer=post_task_observer if config.workflow_skill.enabled else None,
        evolution_cycle_runner=evolution_cycle_runner,
        sandbox_lifecycle=sandbox_lifecycle,
    )

    return ApplicationState(
        config=config,
        models=models,
        repo=repo,
        store=store,
        socm_store=socm_store,
        registry=registry,
        session_service=session_service,
        task_service=task_service,
        skill_store=skill_store,
        workflow_skill_store=workflow_skill_store,
        skill_selector=skill_selector if config.workflow_skill.enabled else None,
        skill_snapshot=skill_snapshot if config.workflow_skill.enabled else None,
        skill_composer=skill_composer,
        skill_files=skill_files,
        post_task_observer=post_task_observer if config.workflow_skill.enabled else None,
        evolution_manager=evolution_manager,
        capability_report=capability_report,
        capability_diagnostics=diagnostics,
        sandbox=sandbox_lifecycle,
    )


def load_config_from_env() -> AppConfig:
    """Read config from .env + env. Loads .env first (does not override real env)."""
    _load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    enabled = os.environ.get("CAPABILITY_PACKAGES_ENABLED")
    enabled_list = (
        [s.strip() for s in enabled.split(",") if s.strip()] if enabled else None
    )
    config = AppConfig(
        sessions_cwd=os.environ.get("SESSIONS_CWD", "competitive_app"),
        sessions_root=os.environ.get("SESSIONS_ROOT", "data/sessions"),
        app_db=os.environ.get("APP_DB", "data/app.db"),
        prompt_lock_timeout=float(os.environ.get("PROMPT_LOCK_TIMEOUT", "30")),
        default_model=os.environ.get("OPENAI_MODEL", ""),
        use_faux=os.environ.get("USE_FAUX", "").lower() in ("1", "true", "yes"),
        sandbox=SandboxAppConfig(
            image=os.environ.get("SANDBOX_IMAGE", ""),
            root=os.environ.get("SANDBOX_ROOT", "data/sandboxes"),
        ),
    )
    if enabled_list is not None:
        config.capability_packages_enabled = enabled_list
    return config


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (setdefault — never overrides real env vars)."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key:
            os.environ.setdefault(key, val)


__all__ = [
    "AppConfig",
    "ApplicationState",
    "SandboxAppConfig",
    "build_application_state",
    "load_config_from_env",
]
