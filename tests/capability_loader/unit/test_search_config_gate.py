"""O2: missing required env → register raises → zero tools + error diagnostic."""
from __future__ import annotations

from pathlib import Path

import pytest

from earendil_works.pi_agent import load_capability_packages

ROOT = Path(__file__).resolve().parents[3]
CAP_ROOT = ROOT / "capability_packages"

PACKAGES = {
    "search_tavily": ["TAVILY_API_KEY"],
    "search_anysearch": ["ANYSEARCH_API_KEY", "ANYSEARCH_API_URL"],
    "search_grok": ["GROK_API_KEY", "GROK_API_URL", "GROK_MODEL"],
}


@pytest.mark.asyncio
@pytest.mark.parametrize("pkg,env_names", list(PACKAGES.items()))
async def test_missing_env_zero_tools_and_error_diagnostic(
    pkg: str,
    env_names: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in env_names:
        monkeypatch.delenv(name, raising=False)
    # Ensure no leakage from .env loaded elsewhere for these keys
    report = await load_capability_packages(root=CAP_ROOT, enabled=[pkg])
    assert report.tool_names() == []
    errors = [d for d in report.diagnostics if d.level == "error"]
    assert errors, report.diagnostics
    joined = " ".join(d.message for d in errors)
    # diagnostic must mention a missing env name and never contain secret-looking values
    assert any(n in joined for n in env_names)
    for d in errors:
        assert "sk-" not in d.message
        assert "Bearer" not in d.message


@pytest.mark.asyncio
async def test_other_packages_still_load_when_search_missing_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for names in PACKAGES.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)
    report = await load_capability_packages(
        root=CAP_ROOT,
        enabled=["echo_example", "search_tavily", "search_anysearch", "search_grok"],
    )
    assert "echo" in report.tool_names()
    for name in (
        "tavily_search",
        "tavily_fetch",
        "anysearch_search",
        "anysearch_fetch",
        "grok_search",
    ):
        assert name not in report.tool_names()
