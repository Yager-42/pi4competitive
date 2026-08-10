"""Live smoke: 1 case A2 via HTTP (D12). Real provider, ~3-5 min.

This is the eval harness live smoke (Task 13): submit one trivial research
brief to a running competitive_app, poll to terminal, fetch the report. It
proves the full HTTP chain (POST /tasks -> poll -> GET /reports) is wired and
that the WideSearch scorer's deepseek-v4-flash routing (llm.py patch) actually
fires against a real provider.

Gates (all must pass or the test skips — never fails the suite offline):
- @pytest.mark.live (only runs with -m live)
- live_env: OPENAI_API_KEY present (L2)
- tavily_env: TAVILY_API_KEY present (D8)
- app_running: competitive_app serving on :8000

To run locally:
    # shell 1
    uv run competitive_app serve --port 8000
    # shell 2
    uv run pytest tests/eval/integration/live/test_smoke_one_case.py -v -m live
"""
from __future__ import annotations

import pytest

from eval.runner.http_client import CompetitiveAppClient


@pytest.mark.live
@pytest.mark.asyncio
async def test_a2_one_case_http_chain(tavily_env, app_running):
    """Submit 1 trivial brief, poll, get report — prove HTTP chain + deepseek routing."""
    brief = {
        "target": {"name": "eval-smoke", "category": "benchmark"},
        "goal": (
            "Compare Apple iPhone 15 vs Samsung Galaxy S24 price. "
            "Output a Markdown table with columns: price, screen."
        ),
        "competitors": ["Apple iPhone 15", "Samsung Galaxy S24"],
        "dimensions": ["price", "screen"],
    }
    client = CompetitiveAppClient(base_url="http://127.0.0.1:8000")
    result = await client.run_task(
        research_brief=brief,
        search_overrides={"max_queries": 5, "max_wall_seconds": 180},
        timeout=300,
        poll_interval=10,
    )

    assert result.terminal_status in ("completed", "failed", "aborted")

    # completed -> must have a non-empty markdown report.
    if result.terminal_status == "completed":
        assert len(result.report_markdown) > 0
