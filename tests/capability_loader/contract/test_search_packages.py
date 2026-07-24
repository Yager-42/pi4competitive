"""O1 + contract: exact tool names; no domain imports; no mcp_package type."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from earendil_works.pi_agent import load_capability_packages

ROOT = Path(__file__).resolve().parents[3]
CAP_ROOT = ROOT / "capability_packages"
SEARCH_PKGS = ["search_tavily", "search_anysearch", "search_grok"]
EXPECTED_TOOLS = {
    "tavily_search",
    "tavily_fetch",
    "anysearch_search",
    "anysearch_fetch",
    "grok_search",
}


def _py_files() -> list[Path]:
    files: list[Path] = []
    for pkg in SEARCH_PKGS:
        files.extend(sorted((CAP_ROOT / pkg).rglob("*.py")))
    return files


def test_search_packages_on_disk() -> None:
    for pkg in SEARCH_PKGS:
        assert (CAP_ROOT / pkg / "package.json").is_file()
        assert list((CAP_ROOT / pkg / "extensions").glob("*.py"))


@pytest.mark.asyncio
async def test_load_registers_exact_tool_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "t-key")
    monkeypatch.setenv("ANYSEARCH_API_KEY", "a-key")
    monkeypatch.setenv("ANYSEARCH_API_URL", "https://api.anysearch.test/mcp")
    monkeypatch.setenv("GROK_API_KEY", "g-key")
    monkeypatch.setenv("GROK_API_URL", "https://api.grok.test/v1")
    monkeypatch.setenv("GROK_MODEL", "grok-test")
    report = await load_capability_packages(root=CAP_ROOT, enabled=SEARCH_PKGS)
    names = set(report.tool_names())
    assert names == EXPECTED_TOOLS
    assert not any(d.level == "error" for d in report.diagnostics), report.diagnostics


def test_no_competitive_app_or_mcp_package_type() -> None:
    offenders: list[str] = []
    for path in _py_files():
        text = path.read_text(encoding="utf-8")
        if "competitive_app" in text:
            offenders.append(f"{path}: competitive_app")
        if "mcp_package" in text:
            offenders.append(f"{path}: mcp_package")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("competitive_app"):
                        offenders.append(f"{path}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("competitive_app"):
                    offenders.append(f"{path}: from {node.module}")
    assert not offenders, offenders


def test_no_shared_package_root_helper_dir() -> None:
    forbidden = [
        CAP_ROOT / "_search_common",
        CAP_ROOT / "search_common",
        CAP_ROOT / "_common",
    ]
    for path in forbidden:
        assert not path.exists(), f"forbidden shared package root: {path}"


def test_package_json_names() -> None:
    import json

    for pkg in SEARCH_PKGS:
        data = json.loads((CAP_ROOT / pkg / "package.json").read_text(encoding="utf-8"))
        assert data["name"] == pkg
        assert "pi-package" in data.get("keywords", [])
        assert data["pi"]["extensions"] == ["./extensions"]
