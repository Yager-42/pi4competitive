"""budget_guard: wrap search/fetch tools, count + reject over budget (D7)."""

from __future__ import annotations

import pytest
from eval.runner.budget_guard import BudgetGuard, wrap_tools_with_budget


class _FakeTool:
    def __init__(self, name):
        self.name = name
        self.parameters = {}
        self.description = ""
        self.execute = None  # filled by wrap


async def _async_ok(*args, **kwargs):
    return {"content": [{"type": "text", "text": "ok"}], "details": {}}


@pytest.mark.asyncio
async def test_budget_guard_counts_search_and_fetch():
    guard = BudgetGuard(max_search=2, max_fetch=4)
    assert guard.search_count == 0
    guard.consume_search()
    guard.consume_search()
    assert guard.search_count == 2
    assert guard.exhausted_search()


@pytest.mark.asyncio
async def test_wrap_rejects_when_search_exhausted():
    guard = BudgetGuard(max_search=1, max_fetch=2)
    tool = _FakeTool("tavily_search")
    tool.execute = _async_ok
    wrapped = guard.wrap(tool)
    # first call ok
    await wrapped.execute("id", {})
    # second call: budget exhausted -> error result
    result = await wrapped.execute("id", {})
    assert result["content"][0]["text"].startswith("budget_exhausted")


def test_wrap_distinguishes_search_vs_fetch():
    guard = BudgetGuard(max_search=2, max_fetch=2)
    search_tool = _FakeTool("tavily_search")
    fetch_tool = _FakeTool("tavily_fetch")
    ws = guard.wrap(search_tool)
    wf = guard.wrap(fetch_tool)
    assert ws.name == "tavily_search"
    assert wf.name == "tavily_fetch"


def test_wrap_tools_with_budget_filters():
    tools = [_FakeTool("tavily_search"), _FakeTool("tavily_fetch"), _FakeTool("echo")]
    guard = BudgetGuard(max_search=5, max_fetch=10)
    wrapped = wrap_tools_with_budget(tools, guard)
    names = [t.name for t in wrapped]
    assert "tavily_search" in names
    assert "tavily_fetch" in names
    assert "echo" in names
