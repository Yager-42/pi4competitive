"""O6: faux agent toolCall → real AgentTool.execute (mock HTTP) → toolResult visible."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from earendil_works.pi_ai import create_models
from earendil_works.pi_ai.providers.faux import (
    faux_assistant_message,
    faux_provider,
    faux_tool_call,
)

from earendil_works.pi_agent import (
    AgentLoopConfig,
    apply_capability_report,
    load_capability_packages,
    run_agent_loop,
)
from earendil_works.pi_agent.types import AgentContext, AgentEvent, AgentMessage

ROOT = Path(__file__).resolve().parents[4]
CAP_ROOT = ROOT / "capability_packages"
FIXTURES = ROOT / "tests/capability_loader/fixtures/search"


def _convert_to_llm(messages: list[AgentMessage]) -> list[Any]:
    return [
        m
        for m in messages
        if isinstance(m, dict) and m.get("role") in ("user", "assistant", "toolResult")
    ]


class _MockResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        json_data: Any = None,
        text: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = text if text or json_data is None else json.dumps(json_data)
        self.headers = headers or {}
        self.request = httpx.Request("POST", "https://example.test")

    def json(self) -> Any:
        return self._json

    async def aread(self) -> bytes:
        return self.text.encode("utf-8")

    async def aiter_lines(self):
        for line in self.text.splitlines():
            yield line


class _MockStreamCM:
    def __init__(self, response: _MockResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _MockResponse:
        return self._response

    async def __aexit__(self, *args: Any) -> None:
        return None


class _MockClient:
    def __init__(self, handler) -> None:
        self._handler = handler

    async def __aenter__(self) -> "_MockClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def post(self, url: str, **kwargs: Any) -> _MockResponse:
        return await self._handler("POST", url, kwargs)

    def stream(self, method: str, url: str, **kwargs: Any) -> _MockStreamCM:
        return _MockStreamCM(self._handler(method, url, kwargs))


async def _run_tool_loop(tool_name: str, arguments: dict[str, Any], tools: list[Any]) -> dict[str, Any]:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"](
        [
            faux_assistant_message([faux_tool_call(tool_name, arguments)]),
            faux_assistant_message("done"),
        ]
    )
    model = faux["getModel"]()
    assert model is not None

    events: list[AgentEvent] = []

    async def emit(event: AgentEvent) -> None:
        events.append(event)

    context: AgentContext = {"systemPrompt": "test", "messages": [], "tools": tools}
    cfg = AgentLoopConfig(model=model, convertToLlm=_convert_to_llm, toolExecution="sequential")
    prompt: AgentMessage = {
        "role": "user",
        "content": f"call {tool_name}",
        "timestamp": int(time.time() * 1000),
    }
    new_messages = await run_agent_loop([prompt], context, cfg, emit, None, models.streamSimple)
    tool_results = [m for m in new_messages if isinstance(m, dict) and m.get("role") == "toolResult"]
    assert tool_results, new_messages
    return tool_results[0]


@pytest.mark.asyncio
async def test_faux_agent_tavily_search(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "t-key")
    fixture = json.loads((FIXTURES / "tavily_search_ok.json").read_text(encoding="utf-8"))

    async def handler(method: str, url: str, kwargs: dict[str, Any]) -> _MockResponse:
        return _MockResponse(json_data=fixture)

    # Patch where httpx is used inside the loaded extension module
    import sys

    report = await load_capability_packages(root=CAP_ROOT, enabled=["search_tavily"])
    assert "tavily_search" in report.tool_names()
    # Find the module that registered tools and patch its httpx
    for mod in list(sys.modules.values()):
        path = getattr(mod, "__file__", "") or ""
        if path.endswith("tavily_tools.py"):
            monkeypatch.setattr(mod.httpx, "AsyncClient", lambda **kw: _MockClient(handler))
            break
    else:
        pytest.fail("tavily_tools module not found in sys.modules")

    tr = await _run_tool_loop("tavily_search", {"query": "AI agents", "max_results": 5}, list(report.tools))
    assert tr.get("isError") is False
    body = " ".join(
        c.get("text", "") for c in (tr.get("content") or []) if isinstance(c, dict)
    )
    assert "search_result.v1" in body
    assert "example.com" in body


@pytest.mark.asyncio
async def test_faux_agent_anysearch_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANYSEARCH_API_KEY", "a-key")
    monkeypatch.setenv("ANYSEARCH_API_URL", "https://api.anysearch.test/mcp")
    extract_fix = json.loads((FIXTURES / "anysearch_extract_ok.json").read_text(encoding="utf-8"))

    async def handler(method: str, url: str, kwargs: dict[str, Any]) -> _MockResponse:
        body = kwargs.get("json") or {}
        m = body.get("method")
        if m == "initialize":
            return _MockResponse(
                json_data={"jsonrpc": "2.0", "id": 1, "result": {}},
                headers={"mcp-session-id": "s1"},
            )
        if m == "notifications/initialized":
            return _MockResponse(json_data={})
        if m == "tools/call":
            return _MockResponse(
                json_data={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {"structuredContent": extract_fix},
                }
            )
        return _MockResponse(status_code=500)

    import sys

    report = await load_capability_packages(root=CAP_ROOT, enabled=["search_anysearch"])
    for mod in list(sys.modules.values()):
        path = getattr(mod, "__file__", "") or ""
        if path.endswith("anysearch_tools.py"):
            monkeypatch.setattr(mod.httpx, "AsyncClient", lambda **kw: _MockClient(handler))
            break
    else:
        pytest.fail("anysearch_tools module not found")

    tr = await _run_tool_loop(
        "anysearch_fetch",
        {"url": "https://example.com/doc"},
        list(report.tools),
    )
    assert tr.get("isError") is False
    body = " ".join(c.get("text", "") for c in (tr.get("content") or []) if isinstance(c, dict))
    assert "fetch_result.v1" in body
    assert "Full body" in body


@pytest.mark.asyncio
async def test_faux_agent_grok_search(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROK_API_KEY", "g-key")
    monkeypatch.setenv("GROK_API_URL", "https://api.grok.test/v1")
    monkeypatch.setenv("GROK_MODEL", "grok-test")
    raw = (FIXTURES / "grok_answer_with_sources.txt").read_text(encoding="utf-8")
    sse = (
        'data: {"choices":[{"delta":{"content":'
        + json.dumps(raw)
        + "}}]}\n"
        + "data: [DONE]\n"
    )

    def handler(method: str, url: str, kwargs: dict[str, Any]) -> _MockResponse:
        return _MockResponse(status_code=200, text=sse)

    import sys

    report = await load_capability_packages(root=CAP_ROOT, enabled=["search_grok"])
    for mod in list(sys.modules.values()):
        path = getattr(mod, "__file__", "") or ""
        if path.endswith("grok_tools.py"):
            monkeypatch.setattr(mod.httpx, "AsyncClient", lambda **kw: _MockClient(handler))
            break
    else:
        pytest.fail("grok_tools module not found")

    tr = await _run_tool_loop("grok_search", {"query": "AI agents"}, list(report.tools))
    assert tr.get("isError") is False
    body = " ".join(c.get("text", "") for c in (tr.get("content") or []) if isinstance(c, dict))
    assert "search_result.v1" in body
    assert "synthesized" in body or "example.com" in body


@pytest.mark.asyncio
async def test_apply_capability_report_merges_search_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "t-key")
    from earendil_works.pi_agent import Agent, AgentOptions

    report = await load_capability_packages(root=CAP_ROOT, enabled=["search_tavily"])
    agent = Agent(AgentOptions(initial_state={"tools": [], "systemPrompt": "x"}))
    apply_capability_report(agent, report)
    names = {t.name for t in agent.state.tools}
    assert "tavily_search" in names
    assert "tavily_fetch" in names
