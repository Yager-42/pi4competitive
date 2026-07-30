"""FastAPI application factory + lifespan.

Contract §6.3: FastAPI route → application → domain + packages/agent + repos.
Routes live in routes_*.py and only call application services (contract G2).

Lifespan failure layering (feature F-A23):
  - Missing provider key: does NOT block startup (surfaced at prompt time).
  - Capability package failure: recorded as diagnostics, does not crash.
  - SQLite / JSONL infra failure: raises → FastAPI startup fails fast.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ....wiring import AppConfig, ApplicationState, build_application_state, load_config_from_env
from .routes_health import router as health_router
from .routes_reports import router as reports_router
from .routes_sessions import router as sessions_router
from .routes_tasks import router as tasks_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config_from_env()
    state = await build_application_state(config)
    app.state.application = state  # type: ignore[attr-defined]
    try:
        yield
    finally:
        await state.shutdown()


def create_app(config: AppConfig | None = None) -> FastAPI:
    app = FastAPI(
        title="CompetitorLens",
        description="P4 competitive_app — FastAPI over earendil_works.pi_agent",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(sessions_router)
    app.include_router(tasks_router)
    app.include_router(reports_router)
    app.include_router(health_router)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"name": "CompetitorLens", "version": "0.1.0", "docs": "/docs"}

    return app


def get_state(app: Any) -> ApplicationState:
    state = getattr(app.state, "application", None)
    if state is None:
        raise RuntimeError("application state not initialized (lifespan not started)")
    return state


__all__ = ["create_app", "get_state", "lifespan"]
