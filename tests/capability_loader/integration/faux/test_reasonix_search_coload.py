from __future__ import annotations

from pathlib import Path

import pytest

from earendil_works.pi_agent import load_capability_packages


ROOT = Path(__file__).parents[4]


@pytest.mark.asyncio
async def test_reasonix_and_search_package_co_load_without_collision() -> None:
    report = await load_capability_packages(
        ROOT / "capability_packages", enabled=["reasonix_prefix_cache", "search_tavily"]
    )
    assert set(report.tool_names()) == {"tavily_search", "tavily_fetch"}
    assert not [diagnostic for diagnostic in report.diagnostics if diagnostic.level == "error"]
    assert report.extension_runner.has_handlers("before_provider_request")
    assert all(callable(tool.execute) for tool in report.tools)
