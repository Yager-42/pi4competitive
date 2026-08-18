"""single_agent_app: A1 ASGI service (D9)."""

from __future__ import annotations

from eval.runner.single_agent_app import create_single_agent_app, _resolve_openai_model
from fastapi.testclient import TestClient


def test_app_has_run_endpoints():
    app = create_single_agent_app()
    with TestClient(app) as client:
        # health
        r = client.get("/eval/health")
        assert r.status_code == 200
        assert r.json()["runtime"] == "single_agent"
        # POST /eval/run returns task_id (202)
        r = client.post(
            "/eval/run",
            json={
                "research_brief": {
                    "target": {"name": "x", "category": "benchmark"},
                    "goal": "Compare A vs B",
                    "competitors": ["A", "B"],
                    "dimensions": ["price"],
                },
                "search_overrides": {"max_queries": 5, "max_fetches": 10, "max_wall_seconds": 60},
            },
        )
        assert r.status_code == 202
        assert "task_id" in r.json()


def test_app_run_poll_completes_with_synthetic_runner(monkeypatch):
    """Inject a fake runner so we test HTTP shape without real LLM."""
    from eval.runner import single_agent_app as saa

    async def fake_run(task_id, brief, overrides):
        return {"markdown": "# table\n|a|b|\n|---|---|\n|1|2|", "status": "completed"}

    monkeypatch.setattr(saa, "_run_single_agent", fake_run)
    app = create_single_agent_app()
    with TestClient(app) as client:
        r = client.post(
            "/eval/run",
            json={
                "research_brief": {
                    "target": {"name": "x", "category": "benchmark"},
                    "goal": "g",
                    "competitors": ["A"],
                    "dimensions": ["d"],
                },
                "search_overrides": {},
            },
        )
        task_id = r.json()["task_id"]
        r = client.get(f"/eval/run/{task_id}")
        assert r.json()["status"] == "completed"
        r = client.get(f"/eval/run/{task_id}/report")
        assert "table" in r.json()["markdown"]


def test_resolve_openai_model_overrides_catalog_base_url(monkeypatch):
    """A1 must use OPENAI_BASE_URL (gateway), not the catalog's api.openai.com."""
    import os

    monkeypatch.setenv("OPENAI_BASE_URL", "https://pro3.o0n0o.cc/v1")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.6-luna")

    class _Models:
        def getModels(self):
            return [
                {
                    "id": "gpt-5.6-luna",
                    "api": "openai-responses",
                    "provider": "openai",
                    "baseUrl": "https://api.openai.com/v1",  # catalog hardcode
                }
            ]

    model = _resolve_openai_model(_Models(), "gpt-5.6-luna")
    assert model["baseUrl"] == "https://pro3.o0n0o.cc/v1"


def test_resolve_openai_model_fallback_dict_uses_gateway(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://pro3.o0n0o.cc/v1")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.6-luna")

    class _Models:
        def getModels(self):
            return []  # not in catalog → synthesize

    model = _resolve_openai_model(_Models(), "gpt-5.6-luna")
    assert model["id"] == "gpt-5.6-luna"
    assert model["baseUrl"] == "https://pro3.o0n0o.cc/v1"


def test_resolve_openai_model_falls_back_to_catalog_first(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    class _Models:
        def getModels(self):
            return [{"id": "catalog-0"}, {"id": "catalog-1"}]

    assert _resolve_openai_model(_Models(), "")["id"] == "catalog-0"
