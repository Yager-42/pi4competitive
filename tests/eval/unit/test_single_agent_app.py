"""single_agent_app: A1 ASGI service (D9)."""
from __future__ import annotations

from eval.runner.single_agent_app import create_single_agent_app
from fastapi.testclient import TestClient


def test_app_has_run_endpoints():
    app = create_single_agent_app()
    with TestClient(app) as client:
        # health
        r = client.get("/eval/health")
        assert r.status_code == 200
        assert r.json()["runtime"] == "single_agent"
        # POST /eval/run returns task_id (202)
        r = client.post("/eval/run", json={
            "research_brief": {
                "target": {"name": "x", "category": "benchmark"},
                "goal": "Compare A vs B",
                "competitors": ["A", "B"],
                "dimensions": ["price"],
            },
            "search_overrides": {"max_queries": 5, "max_fetches": 10, "max_wall_seconds": 60},
        })
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
        r = client.post("/eval/run", json={
            "research_brief": {"target": {"name": "x", "category": "benchmark"},
                               "goal": "g", "competitors": ["A"], "dimensions": ["d"]},
            "search_overrides": {},
        })
        task_id = r.json()["task_id"]
        r = client.get(f"/eval/run/{task_id}")
        assert r.json()["status"] == "completed"
        r = client.get(f"/eval/run/{task_id}/report")
        assert "table" in r.json()["markdown"]
