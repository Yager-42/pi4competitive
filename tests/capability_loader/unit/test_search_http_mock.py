"""O3/O5: param validation blocks HTTP; mock httpx success + hard fail."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
CAP = ROOT / "capability_packages"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "search"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tavily() -> ModuleType:
    return _load(CAP / "search_tavily/extensions/tavily_tools.py", "cap_tavily_http")


@pytest.fixture
def anysearch() -> ModuleType:
    return _load(CAP / "search_anysearch/extensions/anysearch_tools.py", "cap_anysearch_http")


@pytest.fixture
def grok() -> ModuleType:
    return _load(CAP / "search_grok/extensions/grok_tools.py", "cap_grok_http")


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
        if self._json is None:
            raise ValueError("no json")
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
        # sync factory returning async CM — handler must be sync for stream factory
        resp = self._handler(method, url, kwargs)
        if hasattr(resp, "__await__"):
            raise RuntimeError("stream handler must be sync")
        return _MockStreamCM(resp)


@pytest.mark.asyncio
async def test_tavily_search_success_and_param_reject(
    tavily: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    called: list[str] = []
    fixture = json.loads((FIXTURES / "tavily_search_ok.json").read_text(encoding="utf-8"))

    async def handler(method: str, url: str, kwargs: dict[str, Any]) -> _MockResponse:
        called.append(url)
        assert "api_key" in (kwargs.get("json") or {})
        return _MockResponse(json_data=fixture)

    monkeypatch.setattr(
        tavily.httpx,
        "AsyncClient",
        lambda **kw: _MockClient(handler),
    )
    with pytest.raises(tavily.ProviderError):
        await tavily._tavily_search_execute("t1", {"query": "q", "max_results": 99})
    assert called == []

    with pytest.raises(tavily.ProviderError):
        await tavily._tavily_search_execute("t1", {"query": "q", "extra": 1})
    assert called == []

    result = await tavily._tavily_search_execute("t1", {"query": "AI agents", "max_results": 2})
    assert called
    details = result["details"]
    assert details["schema_version"] == "search_result.v1"
    assert len(details["hits"]) == 2
    text = result["content"][0]["text"]
    assert "search_result.v1" in text


@pytest.mark.asyncio
async def test_tavily_fetch_success_and_http_error(
    tavily: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    fixture = json.loads((FIXTURES / "tavily_extract_ok.json").read_text(encoding="utf-8"))
    mode = {"fail": False}

    async def handler(method: str, url: str, kwargs: dict[str, Any]) -> _MockResponse:
        if mode["fail"]:
            return _MockResponse(status_code=500, text="err")
        return _MockResponse(json_data=fixture)

    monkeypatch.setattr(tavily.httpx, "AsyncClient", lambda **kw: _MockClient(handler))
    ok = await tavily._tavily_fetch_execute("t1", {"url": "https://example.com/page"})
    assert ok["details"]["schema_version"] == "fetch_result.v1"
    assert "Complete Markdown" in ok["details"]["content"]

    mode["fail"] = True
    with pytest.raises(tavily.ProviderError):
        await tavily._tavily_fetch_execute("t1", {"url": "https://example.com/page"})


@pytest.mark.asyncio
async def test_anysearch_search_and_fetch_mock(
    anysearch: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANYSEARCH_API_KEY", "k")
    monkeypatch.setenv("ANYSEARCH_API_URL", "https://api.anysearch.test/mcp")
    search_fix = json.loads((FIXTURES / "anysearch_search_ok.json").read_text(encoding="utf-8"))
    extract_fix = json.loads((FIXTURES / "anysearch_extract_ok.json").read_text(encoding="utf-8"))
    calls: list[str] = []

    async def handler(method: str, url: str, kwargs: dict[str, Any]) -> _MockResponse:
        body = kwargs.get("json") or {}
        method_name = body.get("method")
        calls.append(str(method_name))
        if method_name == "initialize":
            return _MockResponse(
                json_data={"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}},
                headers={"mcp-session-id": "sess-1"},
            )
        if method_name == "notifications/initialized":
            return _MockResponse(json_data={})
        if method_name == "tools/call":
            name = (body.get("params") or {}).get("name")
            if name == "search":
                return _MockResponse(
                    json_data={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(search_fix),
                                }
                            ]
                        },
                    }
                )
            if name == "extract":
                return _MockResponse(
                    json_data={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "result": {
                            "structuredContent": extract_fix,
                        },
                    }
                )
        return _MockResponse(status_code=500, text="bad")

    monkeypatch.setattr(anysearch.httpx, "AsyncClient", lambda **kw: _MockClient(handler))

    with pytest.raises(anysearch.ProviderError):
        await anysearch._anysearch_search_execute("t", {"query": "q", "max_results": 0})
    assert "tools/call" not in calls

    s = await anysearch._anysearch_search_execute("t", {"query": "q", "max_results": 5})
    assert s["details"]["provider"] == "anysearch"
    assert len(s["details"]["hits"]) == 3

    f = await anysearch._anysearch_fetch_execute("t", {"url": "https://example.com/doc"})
    assert f["details"]["schema_version"] == "fetch_result.v1"
    assert "Full body" in f["details"]["content"]


@pytest.mark.asyncio
async def test_grok_search_stream_success_and_fail(
    grok: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROK_API_KEY", "k")
    monkeypatch.setenv("GROK_API_URL", "https://api.grok.test/v1")
    monkeypatch.setenv("GROK_MODEL", "grok-test")
    mode = {"fail": False}
    raw = (FIXTURES / "grok_answer_with_sources.txt").read_text(encoding="utf-8")
    # SSE chunks
    sse = (
        'data: {"choices":[{"delta":{"content":'
        + json.dumps(raw[:20])
        + "}}]}\n"
        + 'data: {"choices":[{"delta":{"content":'
        + json.dumps(raw[20:])
        + "}}]}\n"
        + "data: [DONE]\n"
    )

    def handler(method: str, url: str, kwargs: dict[str, Any]) -> _MockResponse:
        if mode["fail"]:
            return _MockResponse(status_code=401, text="no")
        return _MockResponse(status_code=200, text=sse)

    monkeypatch.setattr(grok.httpx, "AsyncClient", lambda **kw: _MockClient(handler))

    with pytest.raises(grok.ProviderError):
        await grok._grok_search_execute("t", {"query": ""})

    ok = await grok._grok_search_execute("t", {"query": "AI agents"})
    assert ok["details"]["provider"] == "grok"
    assert ok["details"]["answer"]
    assert ok["details"]["hits"]

    mode["fail"] = True
    with pytest.raises(grok.ProviderError):
        await grok._grok_search_execute("t", {"query": "AI agents"})
