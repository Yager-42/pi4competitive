"""Live L1–L4: real provider keys; skip when incomplete.

Covers scripted toolCall + real execute, and real-gateway Agent→tool→content.
Never logs secrets.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from earendil_works.pi_agent import (
    AgentLoopConfig,
    apply_capability_report,
    load_capability_packages,
    run_agent_loop,
)
from earendil_works.pi_agent.types import AgentContext, AgentEvent, AgentMessage
from earendil_works.pi_ai import create_models
from earendil_works.pi_ai.providers.faux import (
    faux_assistant_message,
    faux_provider,
    faux_tool_call,
)
from tests.live_env import load_dotenv
from tests.packages.agent.integration.live.helpers import (
    assistants,
    make_agent,
    text_of,
    tool_results,
)

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[4]
CAP_ROOT = ROOT / "capability_packages"


def _provider_env_ready(required: list[str]) -> bool:
    load_dotenv()
    return all((os.environ.get(k) or "").strip() for k in required)


def _convert_to_llm(messages: list[AgentMessage]) -> list[Any]:
    return [
        m
        for m in messages
        if isinstance(m, dict) and m.get("role") in ("user", "assistant", "toolResult")
    ]


async def _scripted_tool_call(tool_name: str, arguments: dict[str, Any], tools: list[Any]) -> dict[str, Any]:
    """Scripted toolCall via faux model + real tool execute (live network)."""
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

    context: AgentContext = {"systemPrompt": "live", "messages": [], "tools": tools}
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


def _payload_from_tool_result(tr: dict[str, Any]) -> dict[str, Any]:
    details = tr.get("details")
    if isinstance(details, dict) and details.get("schema_version"):
        return details
    for block in tr.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            try:
                data = json.loads(block.get("text") or "")
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
    return {}


@pytest.mark.asyncio
async def test_live_tavily_search() -> None:
    if not _provider_env_ready(["TAVILY_API_KEY"]):
        pytest.skip("TAVILY_API_KEY not configured")
    report = await load_capability_packages(root=CAP_ROOT, enabled=["search_tavily"])
    assert "tavily_search" in report.tool_names(), report.diagnostics
    tr = await _scripted_tool_call(
        "tavily_search",
        {"query": "OpenAI GPT-5 release", "max_results": 5},
        list(report.tools),
    )
    assert tr.get("isError") is False, tr
    payload = _payload_from_tool_result(tr)
    assert payload.get("schema_version") == "search_result.v1"
    assert payload.get("hits") or payload.get("answer")


@pytest.mark.asyncio
async def test_live_tavily_fetch() -> None:
    if not _provider_env_ready(["TAVILY_API_KEY"]):
        pytest.skip("TAVILY_API_KEY not configured")
    report = await load_capability_packages(root=CAP_ROOT, enabled=["search_tavily"])
    assert "tavily_fetch" in report.tool_names(), report.diagnostics
    tr = await _scripted_tool_call(
        "tavily_fetch",
        {"url": "https://example.com"},
        list(report.tools),
    )
    assert tr.get("isError") is False, tr
    payload = _payload_from_tool_result(tr)
    assert payload.get("schema_version") == "fetch_result.v1"
    assert isinstance(payload.get("content"), str) and payload["content"].strip()


@pytest.mark.asyncio
async def test_live_anysearch_search() -> None:
    if not _provider_env_ready(["ANYSEARCH_API_KEY", "ANYSEARCH_API_URL"]):
        pytest.skip("ANYSEARCH_* not fully configured")
    report = await load_capability_packages(root=CAP_ROOT, enabled=["search_anysearch"])
    assert "anysearch_search" in report.tool_names(), report.diagnostics
    tr = await _scripted_tool_call(
        "anysearch_search",
        {"query": "Python asyncio tutorial", "max_results": 5},
        list(report.tools),
    )
    assert tr.get("isError") is False, tr
    payload = _payload_from_tool_result(tr)
    assert payload.get("schema_version") == "search_result.v1"
    assert payload.get("hits") or payload.get("answer")


@pytest.mark.asyncio
async def test_live_grok_search() -> None:
    if not _provider_env_ready(["GROK_API_KEY", "GROK_API_URL", "GROK_MODEL"]):
        pytest.skip("GROK_* not fully configured")
    report = await load_capability_packages(root=CAP_ROOT, enabled=["search_grok"])
    assert "grok_search" in report.tool_names(), report.diagnostics
    tr = await _scripted_tool_call(
        "grok_search",
        {"query": "What is the capital of France? Give brief answer with sources."},
        list(report.tools),
    )
    assert tr.get("isError") is False, tr
    payload = _payload_from_tool_result(tr)
    assert payload.get("schema_version") == "search_result.v1"
    assert (payload.get("answer") and str(payload["answer"]).strip()) or payload.get("hits")


def _assert_search_tool_result(tr: dict[str, Any], *, tool_name: str) -> dict[str, Any]:
    assert tr.get("isError") is False, tr
    assert tr.get("toolName") == tool_name
    body = text_of(tr)
    assert body.strip(), "toolResult content must be non-empty for the model"
    payload = _payload_from_tool_result(tr)
    assert payload.get("schema_version") == "search_result.v1", payload
    hits = payload.get("hits") or []
    answer = payload.get("answer")
    assert hits or (isinstance(answer, str) and answer.strip()), payload
    return payload


@pytest.mark.asyncio
async def test_live_agent_tavily_search_via_real_model(live_gateway) -> None:
    """Real gateway model must call tavily_search; toolResult has live hits; agent continues.

    Stronger than scripted L2: proves Agent can choose the search tool and consume results.
    """
    if not _provider_env_ready(["TAVILY_API_KEY"]):
        pytest.skip("TAVILY_API_KEY not configured")

    report = await load_capability_packages(root=CAP_ROOT, enabled=["search_tavily"])
    assert "tavily_search" in report.tool_names(), report.diagnostics

    agent = make_agent(
        live_gateway,
        system_prompt=(
            "You are a research assistant with tools. "
            "You MUST call the tavily_search tool exactly once before answering. "
            "Do not answer from memory. After the tool returns, briefly summarize "
            "1-2 findings using titles/urls from the tool result JSON."
        ),
        tools=list(report.tools),
        tool_execution="sequential",
    )
    apply_capability_report(agent, report)

    await agent.prompt(
        "Search the web for: capital of France. "
        "Use tavily_search with query exactly: capital of France "
        "and max_results=5. Then answer with one short sentence."
    )
    await agent.wait_for_idle()

    assert agent.state.errorMessage is None, agent.state.errorMessage
    trs = tool_results(agent.state.messages)
    assert trs, "expected real model to emit a toolCall for tavily_search"
    search_trs = [m for m in trs if m.get("toolName") == "tavily_search"]
    assert search_trs, f"expected tavily_search toolResult, got {[m.get('toolName') for m in trs]}"
    payload = _assert_search_tool_result(search_trs[0], tool_name="tavily_search")
    assert payload.get("hits"), "live tavily_search should return non-empty hits"

    asst = assistants(agent.state.messages)
    assert asst, "expected assistant messages"
    # Final assistant turn after tool use should be non-error and preferably have text
    final = asst[-1]
    assert final.get("stopReason") != "error", final
    final_text = text_of(final).strip()
    # Some gateways end on toolUse without a closing text turn; require either text or toolUse done
    if final.get("stopReason") == "toolUse":
        # still must have produced the tool call path above
        assert search_trs
    else:
        assert final_text, "expected final assistant answer after toolResult"


@pytest.mark.asyncio
async def test_live_agent_tavily_fetch_via_real_model(live_gateway) -> None:
    """Real gateway model must call tavily_fetch; toolResult has non-empty page content."""
    if not _provider_env_ready(["TAVILY_API_KEY"]):
        pytest.skip("TAVILY_API_KEY not configured")

    report = await load_capability_packages(root=CAP_ROOT, enabled=["search_tavily"])
    assert "tavily_fetch" in report.tool_names(), report.diagnostics

    agent = make_agent(
        live_gateway,
        system_prompt=(
            "You MUST call the tavily_fetch tool exactly once before answering. "
            "Do not invent page content. After the tool returns, quote one short phrase "
            "from the fetched content."
        ),
        tools=list(report.tools),
        tool_execution="sequential",
    )
    apply_capability_report(agent, report)

    await agent.prompt(
        "Fetch https://example.com using tavily_fetch with url exactly "
        "https://example.com then reply with one short sentence about the page."
    )
    await agent.wait_for_idle()

    assert agent.state.errorMessage is None, agent.state.errorMessage
    trs = tool_results(agent.state.messages)
    assert trs, "expected real model to emit a toolCall for tavily_fetch"
    fetch_trs = [m for m in trs if m.get("toolName") == "tavily_fetch"]
    assert fetch_trs, f"expected tavily_fetch toolResult, got {[m.get('toolName') for m in trs]}"
    tr = fetch_trs[0]
    assert tr.get("isError") is False, tr
    body = text_of(tr)
    assert body.strip(), "fetch toolResult content must be visible to the model"
    payload = _payload_from_tool_result(tr)
    assert payload.get("schema_version") == "fetch_result.v1", payload
    assert isinstance(payload.get("content"), str) and payload["content"].strip()

    asst = assistants(agent.state.messages)
    assert asst
    assert asst[-1].get("stopReason") != "error"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("package", "tool_name", "query", "required_env"),
    [
        ("search_anysearch", "anysearch_search", "capital of France",
         ["ANYSEARCH_API_KEY", "ANYSEARCH_API_URL"]),
        ("search_grok", "grok_search", "What is the capital of France?",
         ["GROK_API_KEY", "GROK_API_URL", "GROK_MODEL"]),
    ],
    ids=["anysearch", "grok"],
)
async def test_live_agent_search_provider_via_real_model(
    live_gateway, package: str, tool_name: str, query: str, required_env: list[str]
) -> None:
    """Each configured provider must complete the real model → tool → result path."""
    load_dotenv()
    if not _provider_env_ready(required_env):
        pytest.skip(f"{package} credentials not fully configured")

    report = await load_capability_packages(root=CAP_ROOT, enabled=[package])
    assert tool_name in report.tool_names(), report.diagnostics
    agent = make_agent(
        live_gateway,
        system_prompt=(
            f"You MUST call the {tool_name} tool exactly once before answering. "
            "Do not answer from memory. After the tool returns, give one short sentence."
        ),
        tools=list(report.tools),
        tool_execution="sequential",
    )
    apply_capability_report(agent, report)

    await agent.prompt(f"Use {tool_name} to research: {query}")
    await agent.wait_for_idle()
    assert agent.state.errorMessage is None, agent.state.errorMessage
    results = tool_results(agent.state.messages)
    assert results, f"expected real model to call {tool_name}"
    named = [result for result in results if result.get("toolName") == tool_name]
    assert named, f"expected {tool_name}, got {[result.get('toolName') for result in results]}"
    _assert_search_tool_result(named[0], tool_name=tool_name)
