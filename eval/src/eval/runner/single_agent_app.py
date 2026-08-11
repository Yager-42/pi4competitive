"""A1 single_agent ASGI service (D9).

复用 competitive_app.wiring._HarnessFactory + search_tavily capability,
裸 agent_loop (不进 ResearchRunner/CoverageEngine). 独立 ASGI 服务,
POST /eval/run + GET /eval/run/{task_id} + /report. budget guard 限
search/fetch (D7). 不装 coding tools (D6 闸1).

Unit tests (Task 7) monkeypatch ``_run_single_agent`` so the real agent
wiring in ``_wired_run`` is NOT exercised here — it is verified in Task 13
(live smoke). The wiring below is a best-effort skeleton written against
the real API as read from:
  - competitive_app/wiring.py _HarnessFactory.build_ephemeral (lines 311-402)
  - packages/agent/.../harness/agent_harness.py AgentHarness
  - packages/agent/.../agent.py Agent.prompt / wait_for_idle / state.messages
  - packages/agent/.../package_manager load_capability_packages → LoadReport.tools
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .budget_guard import BudgetGuard, wrap_tools_with_budget

app_state: dict[str, Any] = {"tasks": {}}


class _Brief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: dict[str, str]
    goal: str = Field(min_length=1)
    competitors: list[str] = Field(min_length=1)
    dimensions: list[str] = Field(min_length=1)


class _RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    research_brief: _Brief
    search_overrides: dict[str, Any] | None = None


def create_single_agent_app() -> FastAPI:
    app = FastAPI(title="eval single_agent (A1)", version="0.0.1")

    @app.get("/eval/health")
    async def health():
        return {"status": "ok", "runtime": "single_agent", "active": len(app_state["tasks"])}

    @app.post("/eval/run", status_code=202)
    async def run(body: _RunRequest):
        task_id = f"a1-{uuid.uuid4().hex[:8]}"
        app_state["tasks"][task_id] = {"status": "running", "markdown": ""}

        async def _bg():
            try:
                result = await _run_single_agent(
                    task_id, body.research_brief, body.search_overrides or {}
                )
                if isinstance(result, dict):
                    app_state["tasks"][task_id]["status"] = result.get("status", "completed")
                    app_state["tasks"][task_id]["markdown"] = result.get("markdown", "")
            except TimeoutError:
                import traceback
                app_state["tasks"][task_id]["status"] = "failed"
                app_state["tasks"][task_id]["markdown"] = (
                    f"# error: timeout\n\n{traceback.format_exc()}"
                )
            except Exception as exc:  # noqa: BLE001 — never leave task hanging in "running"
                import traceback
                app_state["tasks"][task_id]["status"] = "failed"
                app_state["tasks"][task_id]["markdown"] = (
                    f"# error: {type(exc).__name__}: {exc}\n\n{traceback.format_exc()}"
                )

        asyncio.create_task(_bg())
        return {"task_id": task_id, "status": "running"}

    @app.get("/eval/run/{task_id}")
    async def status(task_id: str):
        t = app_state["tasks"].get(task_id)
        if not t:
            return JSONResponse(status_code=404, content={"error": "not found"})
        return {"task_id": task_id, "status": t["status"]}

    @app.get("/eval/run/{task_id}/report")
    async def report(task_id: str):
        t = app_state["tasks"].get(task_id)
        if not t:
            return JSONResponse(status_code=404, content={"error": "not found"})
        return {"task_id": task_id, "markdown": t.get("markdown", ""), "status": t["status"]}

    return app


async def _run_single_agent(
    task_id: str, brief: _Brief, overrides: dict[str, Any]
) -> dict[str, Any]:
    """Build harness via _HarnessFactory + search_tavily, run bare agent_loop.

    D6 闸1: only search_tavily loaded, no coding tools.
    D7: budget_guard wraps tavily_search/tavily_fetch.
    D9: prompt = "use tools, budget N search + M fetch, output Markdown table".
    """
    max_search = int(overrides.get("max_queries", 20))
    max_fetch = int(overrides.get("max_fetches", 40))
    max_wall = int(overrides.get("max_wall_seconds", 720))

    markdown = await _wired_run(brief, max_search, max_fetch, max_wall)
    app_state["tasks"][task_id]["status"] = "completed"
    app_state["tasks"][task_id]["markdown"] = markdown
    return {"markdown": markdown, "status": "completed"}


async def _wired_run(brief: _Brief, max_search: int, max_fetch: int, max_wall: int) -> str:
    """Real wiring: assemble harness + search_tavily + budget guard + agent loop.

    Mirrors ``_HarnessFactory.build_ephemeral`` (wiring.py:311) but standalone:
      - InMemorySessionRepo (no JSONL persistence — eval harness is ephemeral)
      - tools passed directly (capability_report=None — shared runtime never attached)
      - budget guard wraps tavily_search/tavily_fetch (D7)
      - single harness.prompt with a table-output instruction (D9), no stage DAG

    NOTE: This is the real agent wiring. The unit tests (Task 7) monkeypatch
    ``_run_single_agent`` (the caller), so this function is NOT exercised by
    unit tests. It is verified in Task 13 (live smoke test). If the real
    AgentHarness/Agent API differs from what's written here, fix it during
    Task 13 — for now this is the best-effort wiring based on reading the real
    API (see imports + research_runner.py / wiring.py references).
    """
    from earendil_works.pi_agent import AgentHarness
    from earendil_works.pi_agent.harness.session.memory_repo import InMemorySessionRepo
    from earendil_works.pi_agent.package_manager import load_capability_packages
    from earendil_works.pi_ai import create_models
    from earendil_works.pi_ai.providers.openai import openai_provider

    # D6 闸1: only search_tavily, no coding tools (create_read_tool etc.)
    cap_root = os.environ.get("CAPABILITY_PACKAGES_ROOT", "capability_packages")
    report = await load_capability_packages(root=cap_root, enabled=["search_tavily"])
    tools: list[Any] = list(getattr(report, "tools", []) or [])

    # D7: wrap search/fetch tools with budget guard (other tools pass through)
    guard = BudgetGuard(max_search=max_search, max_fetch=max_fetch)
    tools = wrap_tools_with_budget(tools, guard)

    # model: OpenAI provider (env OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL)
    models = create_models()
    models.setProvider(openai_provider())
    model_id = os.environ.get("OPENAI_MODEL", "")
    if model_id:
        # resolve via the static catalog if present
        candidates = [m for m in models.getModels() if m.get("id") == model_id]
        model: dict[str, Any] = (
            candidates[0]
            if candidates
            else {
                "id": model_id,
                "name": model_id,
                "api": "openai-completions",
                "provider": "openai",
                "baseUrl": os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1",
                "reasoning": False,
                "input": ["text", "image"],
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                "contextWindow": int(os.environ.get("MODEL_CONTEXT_WINDOW_TOKENS") or "128000"),
                "maxTokens": 8192,
            }
        )
    else:
        # fall back to the first catalog model (Task 13 will pin a real id)
        catalog = models.getModels()
        if not catalog:
            raise RuntimeError(
                "no OPENAI_MODEL configured and catalog is empty — set OPENAI_MODEL for Task 13 live"
            )
        model = catalog[0]

    repo = InMemorySessionRepo()
    session = await repo.create({"cwd": "ephemeral"})

    system_prompt = _build_system_prompt(brief, max_search, max_fetch, max_wall)
    harness = AgentHarness(
        session=session,
        stream_fn=models.streamSimple,
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        # capability_report=None: never attach the shared ExtensionRuntime —
        # tools are passed directly (mirrors build_ephemeral).
        capability_report=None,
    )

    prompt = _build_user_prompt(brief, max_search, max_fetch, max_wall)
    # bare agent_loop — no CoverageEngine, no stage DAG (D9).
    await asyncio.wait_for(harness.prompt(prompt), timeout=max_wall)

    # collect last assistant message text as the markdown report
    markdown = _last_assistant_text(harness.agent.state.messages)
    if not markdown:
        markdown = "# (no output)\n"
    return markdown


def _build_system_prompt(brief: _Brief, max_search: int, max_fetch: int, max_wall: int) -> str:
    """D9 system prompt: tool-use + budget + Markdown table output contract."""
    return (
        "You are a competitive-research analyst. Use the provided search and "
        "fetch tools to gather evidence, then output a single Markdown report.\n"
        f"Budget: at most {max_search} searches and {max_fetch} fetches "
        f"(wall clock {max_wall}s). Stop searching when you have enough.\n"
        "Output ONLY a Markdown table comparing the target against its "
        "competitors across the requested dimensions, followed by a short "
        "summary. Cite sources inline as [1], [2] matching the URLs you fetched."
    )


def _build_user_prompt(brief: _Brief, max_search: int, max_fetch: int, max_wall: int) -> str:
    """D9 user prompt: the research brief + output instruction."""
    brief_json = brief.model_dump(mode="json")
    return (
        f"Research brief:\n{json.dumps(brief_json, ensure_ascii=False, indent=2)}\n\n"
        f"Now use the tools (budget: {max_search} searches, {max_fetch} fetches, "
        f"{max_wall}s wall) to research this brief, then output the Markdown "
        "comparison table + summary."
    )


def _last_assistant_text(messages: list[Any]) -> str:
    """Extract text from the last assistant message (mirrors research_runner)."""
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "assistant":
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


__all__ = ["create_single_agent_app"]


def main() -> int:
    """CLI launcher: uv run python -m eval.runner.single_agent_app --port 8001 (D9)."""
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(prog="eval.runner.single_agent_app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    # Load .env so OPENAI_API_KEY / TAVILY_API_KEY / OPENAI_MODEL reach the worker.
    # Reuses tests/live_env.py loader (same setdefault semantics as serve_app.py).
    import sys
    root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(root / "tests"))
    try:
        from live_env import load_dotenv

        load_dotenv(root / ".env")
    except ImportError:
        pass

    try:
        import uvicorn
    except ImportError as exc:
        print(f"uvicorn not installed: {exc}", file=sys.stderr)
        return 1

    app = create_single_agent_app()
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
