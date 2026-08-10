"""budget_guard: A1 工具 wrapper (D7).

wrap tavily_search/tavily_fetch, 计 search_count/fetch_count, 超额返回
budget_exhausted error (让 agent 收手). 其他工具 (echo 等) 原样透传.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

_SEARCH_TOOL_NAMES = {"tavily_search", "anysearch_search", "grok_search"}
_FETCH_TOOL_NAMES = {"tavily_fetch", "anysearch_fetch", "grok_fetch"}


@dataclass
class BudgetGuard:
    max_search: int
    max_fetch: int
    search_count: int = 0
    fetch_count: int = 0

    def exhausted_search(self) -> bool:
        return self.search_count >= self.max_search

    def exhausted_fetch(self) -> bool:
        return self.fetch_count >= self.max_fetch

    def consume_search(self) -> None:
        self.search_count += 1

    def consume_fetch(self) -> None:
        self.fetch_count += 1

    def wrap(self, tool: Any) -> Any:
        """Wrap a single tool with budget counting."""
        name = getattr(tool, "name", "")
        if name in _SEARCH_TOOL_NAMES:
            return _wrap_tool(tool, self, is_search=True)
        if name in _FETCH_TOOL_NAMES:
            return _wrap_tool(tool, self, is_search=False)
        return tool  # non-search/fetch: pass through (D6 闸1: no read/write/bash)


def _wrap_tool(tool: Any, guard: BudgetGuard, *, is_search: bool) -> Any:
    """Return a tool-like object whose execute checks budget first."""
    original_execute = tool.execute
    kind = "search" if is_search else "fetch"

    async def _execute(tool_call_id, params, signal=None, on_update=None):  # type: ignore[no-untyped-def]
        if is_search:
            if guard.exhausted_search():
                return _budget_exhausted_result(kind, guard)
            guard.consume_search()
        else:
            if guard.exhausted_fetch():
                return _budget_exhausted_result(kind, guard)
            guard.consume_fetch()
        return await original_execute(tool_call_id, params, signal, on_update)

    # shallow copy with overridden execute
    wrapped = copy.copy(tool)
    wrapped.execute = _execute  # type: ignore[attr-defined]
    return wrapped


def _budget_exhausted_result(kind: str, guard: BudgetGuard) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": f"budget_exhausted: {kind} limit reached "
                f"(search={guard.search_count}/{guard.max_search}, "
                f"fetch={guard.fetch_count}/{guard.max_fetch})",
            }
        ],
        "details": {"budget_exhausted": True, "kind": kind},
    }


def wrap_tools_with_budget(tools: list[Any], guard: BudgetGuard) -> list[Any]:
    """Wrap all search/fetch tools in the list; pass through others."""
    return [guard.wrap(t) for t in tools]


__all__ = ["BudgetGuard", "wrap_tools_with_budget"]
