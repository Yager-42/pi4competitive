"""P3 C2 live: load capability_packages/echo_example → real gateway tool call.

Never logs secrets. Skips when no API key (via live_gateway fixture).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from earendil_works.pi_agent import apply_capability_report, load_capability_packages
from tests.packages.agent.integration.live.helpers import (
    assistants,
    make_agent,
    text_of,
    tool_results,
)

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[4]
CAP_ROOT = ROOT / "capability_packages"


@pytest.mark.asyncio
async def test_live_load_echo_example_package() -> None:
    """Loader path works without needing the model (still marked live suite family)."""
    report = await load_capability_packages(root=CAP_ROOT, enabled=["echo_example"])
    assert "echo" in report.tool_names()
    assert not any(d.level == "error" for d in report.diagnostics), report.diagnostics
    echo = next(t for t in report.tools if t.name == "echo")
    result = await echo.execute("live-tid", {"text": "cap-live-direct"})
    body = " ".join(
        c.get("text", "") for c in (result.get("content") or []) if isinstance(c, dict)
    )
    assert "cap-live-direct" in body
    assert result.get("details", {}).get("package") == "echo_example"


@pytest.mark.asyncio
async def test_live_capability_echo_via_agent(live_gateway) -> None:
    """Real gateway: Agent must call capability package echo tool."""
    report = await load_capability_packages(root=CAP_ROOT, enabled=["echo_example"])
    assert "echo" in report.tool_names()

    agent = make_agent(
        live_gateway,
        system_prompt=(
            "You MUST call the echo tool. Do not answer without a tool call. "
            "Call echo with text exactly: cap-live-ok"
        ),
        tools=list(report.tools),
        tool_execution="sequential",
    )
    # Also exercise apply path (merge into existing tools)
    apply_capability_report(agent, report)

    await agent.prompt("Use the echo tool to echo exactly: cap-live-ok")
    await agent.wait_for_idle()

    assert agent.state.errorMessage is None, agent.state.errorMessage
    tr = tool_results(agent.state.messages)
    assert tr, "real model did not issue the required capability tool call"
    body = " ".join(text_of(m) for m in tr)
    assert "cap-live-ok" in body
    assert any(not m.get("isError") for m in tr)
    assert any(m.get("toolName") == "echo" for m in tr)


@pytest.mark.asyncio
async def test_live_capability_echo_load_then_apply(live_gateway) -> None:
    """load → apply_capability_report → prompt (empty initial tools)."""
    report = await load_capability_packages(root=CAP_ROOT, enabled=["echo_example"])

    agent = make_agent(
        live_gateway,
        system_prompt=(
            "You MUST call the echo tool with text exactly: apply-live. "
            "Do not answer without a tool call."
        ),
        tools=[],
        tool_execution="sequential",
    )
    diags = apply_capability_report(agent, report)
    assert any(t.name == "echo" for t in agent.state.tools)
    assert not any(d.level == "error" for d in diags)

    await agent.prompt("Call echo with text: apply-live")
    await agent.wait_for_idle()

    assert agent.state.errorMessage is None, agent.state.errorMessage
    tr = tool_results(agent.state.messages)
    assert tr, "real model did not issue the required capability tool call"
    body = " ".join(text_of(m) for m in tr)
    assert "apply-live" in body
    assert any(not m.get("isError") for m in tr)
