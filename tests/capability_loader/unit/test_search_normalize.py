"""O4: normalize fixtures → search_result.v1 / fetch_result.v1."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "search"
CAP = ROOT / "capability_packages"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def tavily() -> ModuleType:
    return _load(CAP / "search_tavily/extensions/tavily_tools.py", "cap_tavily_tools")


@pytest.fixture(scope="module")
def anysearch() -> ModuleType:
    return _load(CAP / "search_anysearch/extensions/anysearch_tools.py", "cap_anysearch_tools")


@pytest.fixture(scope="module")
def grok() -> ModuleType:
    return _load(CAP / "search_grok/extensions/grok_tools.py", "cap_grok_tools")


def test_tavily_search_normalize(tavily: ModuleType) -> None:
    data = json.loads((FIXTURES / "tavily_search_ok.json").read_text(encoding="utf-8"))
    out = tavily.normalize_search_hits("AI agents", data, max_results=10)
    assert out["schema_version"] == "search_result.v1"
    assert out["provider"] == "tavily"
    assert out["query"] == "AI agents"
    assert out["answer"] is None
    assert len(out["hits"]) == 2
    assert out["hits"][0]["canonical_url"] == out["hits"][0]["url"]
    assert out["hits"][0]["url"] == "https://example.com/page?utm_source=x"
    assert out["hits"][0]["rank"] == 1
    assert out["hits"][0]["score"] == 0.91
    assert any(w["code"] == "invalid_provider_item" for w in out["warnings"])


def test_tavily_search_empty_hits(tavily: ModuleType) -> None:
    out = tavily.normalize_search_hits("q", {"results": []}, max_results=5)
    assert out["hits"] == []
    assert out["warnings"] == []


def test_tavily_fetch_normalize(tavily: ModuleType) -> None:
    data = json.loads((FIXTURES / "tavily_extract_ok.json").read_text(encoding="utf-8"))
    out = tavily.normalize_fetch("https://example.com/page", data)
    assert out["schema_version"] == "fetch_result.v1"
    assert out["provider"] == "tavily"
    assert out["canonical_url"] == out["url"]
    assert "Complete Markdown" in out["content"]
    assert out["content_type"] == "markdown"
    assert "truncated" not in out


def test_tavily_fetch_empty_raises(tavily: ModuleType) -> None:
    with pytest.raises(tavily.ProviderError):
        tavily.normalize_fetch("https://example.com", {"results": [{"raw_content": ""}]})


def test_anysearch_search_normalize(anysearch: ModuleType) -> None:
    data = json.loads((FIXTURES / "anysearch_search_ok.json").read_text(encoding="utf-8"))
    out = anysearch.normalize_search("q", data, max_results=10)
    assert out["schema_version"] == "search_result.v1"
    assert len(out["hits"]) == 3
    assert all(h["canonical_url"] == h["url"] for h in out["hits"])
    assert out["warnings"] == []


def test_anysearch_live_markdown_search_parse(anysearch: ModuleType) -> None:
    text = (
        "## Search Results (2 results, 100ms)\n\n"
        "### 1. asyncio docs\n"
        "- **URL**: https://docs.python.org/3/library/asyncio.html\n"
        "- asyncio is a library to write concurrent code\n\n"
        "### 2. Real Python\n"
        "- **URL**: https://realpython.com/async-io-python/\n"
        "- Async IO in Python guide\n"
    )
    items = anysearch._parse_anysearch_markdown_search(text)
    assert len(items) == 2
    assert items[0]["url"].startswith("https://docs.python.org")
    out = anysearch.normalize_search("q", {"results": items}, max_results=10)
    assert len(out["hits"]) == 2
    assert out["hits"][0]["canonical_url"] == out["hits"][0]["url"]


def test_anysearch_fetch_normalize(anysearch: ModuleType) -> None:
    data = json.loads((FIXTURES / "anysearch_extract_ok.json").read_text(encoding="utf-8"))
    out = anysearch.normalize_fetch("https://example.com/doc", data)
    assert out["schema_version"] == "fetch_result.v1"
    assert out["provider"] == "anysearch"
    assert out["title"] == "Fetched Doc"
    assert out["canonical_url"] == out["url"]


def test_grok_answer_and_sources(grok: ModuleType) -> None:
    raw = (FIXTURES / "grok_answer_with_sources.txt").read_text(encoding="utf-8")
    out = grok.normalize_grok_result("AI agents", raw)
    assert out["schema_version"] == "search_result.v1"
    assert out["provider"] == "grok"
    assert out["answer"] and "synthesized" in out["answer"]
    assert len(out["hits"]) >= 2
    assert all(h["canonical_url"] == h["url"] for h in out["hits"])
    assert out["warnings"] == []


def test_grok_answer_without_sources_warning(grok: ModuleType) -> None:
    out = grok.normalize_grok_result("q", "Only an answer, no links.")
    assert out["answer"]
    assert out["hits"] == []
    assert any(w["code"] == "sources_unavailable" for w in out["warnings"])
