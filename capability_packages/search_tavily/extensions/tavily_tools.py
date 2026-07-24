"""search_tavily capability: tavily_search + tavily_fetch AgentTools.

Provider config from env only (F-S9). Thin httpx adapter (F-S17).
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx

from earendil_works.pi_agent.types import AgentTool, AgentToolResult

_DEFAULT_API_URL = "https://api.tavily.com"
_TIMEOUT = httpx.Timeout(connect=6.0, write=10.0, read=120.0, pool=None)

_SEARCH_PARAMS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "query": {"type": "string", "description": "Non-empty search query"},
        "max_results": {
            "type": "integer",
            "description": "Max hits (1..20)",
            "default": 10,
            "minimum": 1,
            "maximum": 20,
        },
        "topic": {
            "type": "string",
            "description": "general | news",
            "default": "general",
            "enum": ["general", "news"],
        },
        "search_depth": {
            "type": "string",
            "description": "basic | advanced",
            "default": "basic",
            "enum": ["basic", "advanced"],
        },
        "time_range": {
            "type": "string",
            "description": "any | day | week | month | year",
            "default": "any",
            "enum": ["any", "day", "week", "month", "year"],
        },
        "include_domains": {
            "type": "array",
            "description": "Up to 20 domain filters",
            "items": {"type": "string"},
            "default": [],
            "maxItems": 20,
        },
    },
    "required": ["query"],
}

_FETCH_PARAMS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "url": {"type": "string", "description": "Full HTTP/HTTPS URL to extract"},
    },
    "required": ["url"],
}


class ProviderError(RuntimeError):
    """Sanitized provider/config failure (no secrets, no raw body)."""


class AbortedError(RuntimeError):
    """Propagated abort; must not be wrapped as a normal provider error."""


def _env_required(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise ProviderError(f"missing required env: {name}")
    return value


def _api_base() -> str:
    return (os.environ.get("TAVILY_API_URL") or _DEFAULT_API_URL).rstrip("/")


def _check_aborted(signal: Any) -> None:
    if signal is not None and bool(getattr(signal, "aborted", False)):
        raise AbortedError("aborted")


def _tool_result(payload: dict[str, Any]) -> AgentToolResult:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "details": payload,
    }


def _warning(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _as_str(value: Any, default: str = "") -> str:
    if isinstance(value, str):
        return value
    return default


def _as_score(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def normalize_search_hits(
    query: str,
    data: dict[str, Any],
    *,
    max_results: int,
) -> dict[str, Any]:
    """Map Tavily /search JSON → search_result.v1."""
    warnings: list[dict[str, str]] = []
    raw_items = data.get("results")
    if not isinstance(raw_items, list):
        raise ProviderError("provider response could not be parsed")

    hits: list[dict[str, Any]] = []
    rejected = 0
    for item in raw_items:
        if len(hits) >= max_results:
            break
        if not isinstance(item, dict):
            rejected += 1
            continue
        url = _as_str(item.get("url")).strip()
        if not url.startswith(("http://", "https://")):
            rejected += 1
            continue
        title = _as_str(item.get("title")).strip() or url
        snippet = _as_str(item.get("content") or item.get("snippet"))
        published = item.get("published_date") or item.get("published_at")
        published_at = _as_str(published).strip() or None
        hits.append(
            {
                "rank": len(hits) + 1,
                "title": title,
                "url": url,
                "canonical_url": url,
                "snippet": snippet,
                "score": _as_score(item.get("score")),
                "published_at": published_at,
            }
        )
    if rejected:
        warnings.append(
            _warning("invalid_provider_item", "Some provider items could not be normalized")
        )
    return {
        "schema_version": "search_result.v1",
        "provider": "tavily",
        "query": query,
        "answer": None,
        "hits": hits,
        "warnings": warnings,
    }


def normalize_fetch(url: str, data: dict[str, Any]) -> dict[str, Any]:
    """Map Tavily /extract JSON → fetch_result.v1."""
    warnings: list[dict[str, str]] = []
    results = data.get("results")
    if not isinstance(results, list) or not results:
        raise ProviderError("fetch returned empty content")
    first = results[0]
    if not isinstance(first, dict):
        raise ProviderError("fetch returned empty content")
    content = first.get("raw_content") or first.get("content") or first.get("text")
    if not isinstance(content, str) or not content.strip():
        raise ProviderError("fetch returned empty content")
    out_url = _as_str(first.get("url"), url).strip() or url
    title = _as_str(first.get("title")).strip()
    content_type = "markdown" if content.lstrip().startswith("#") else "text"
    if data.get("failed_results"):
        warnings.append(
            _warning("partial_provider_response", "Provider reported partial extract failures")
        )
    return {
        "schema_version": "fetch_result.v1",
        "provider": "tavily",
        "url": out_url,
        "canonical_url": out_url,
        "title": title,
        "content": content,
        "content_type": content_type,
        "warnings": warnings,
    }


def _validate_search_params(params: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ProviderError("invalid arguments")
    extra = set(params) - set(_SEARCH_PARAMS["properties"])
    if extra:
        raise ProviderError(f"unexpected properties: {sorted(extra)}")
    query = _as_str(params.get("query")).strip()
    if not query:
        raise ProviderError("query must be a non-empty string")
    max_results = params.get("max_results", 10)
    if not isinstance(max_results, int) or isinstance(max_results, bool) or not (1 <= max_results <= 20):
        raise ProviderError("max_results must be an integer in 1..20")
    topic = params.get("topic", "general")
    if topic not in ("general", "news"):
        raise ProviderError("topic must be general or news")
    search_depth = params.get("search_depth", "basic")
    if search_depth not in ("basic", "advanced"):
        raise ProviderError("search_depth must be basic or advanced")
    time_range = params.get("time_range", "any")
    if time_range not in ("any", "day", "week", "month", "year"):
        raise ProviderError("time_range must be any|day|week|month|year")
    include_domains = params.get("include_domains", [])
    if include_domains is None:
        include_domains = []
    if not isinstance(include_domains, list) or len(include_domains) > 20:
        raise ProviderError("include_domains must be a list of at most 20 domains")
    domains: list[str] = []
    for d in include_domains:
        if not isinstance(d, str) or not d.strip():
            raise ProviderError("include_domains entries must be non-empty strings")
        domains.append(d.strip())
    return {
        "query": query,
        "max_results": max_results,
        "topic": topic,
        "search_depth": search_depth,
        "time_range": time_range,
        "include_domains": domains,
    }


def _validate_fetch_params(params: dict[str, Any]) -> str:
    if not isinstance(params, dict):
        raise ProviderError("invalid arguments")
    extra = set(params) - {"url"}
    if extra:
        raise ProviderError(f"unexpected properties: {sorted(extra)}")
    url = _as_str(params.get("url")).strip()
    if not url:
        raise ProviderError("url must be a non-empty string")
    return url


async def _post_json(
    path: str,
    payload: dict[str, Any],
    *,
    api_key: str,
    signal: Any,
) -> dict[str, Any]:
    _check_aborted(signal)
    url = f"{_api_base()}{path}"
    # api_key is in body for Tavily REST; never log it
    body = {**payload, "api_key": api_key}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            _check_aborted(signal)
            resp = await client.post(
                url,
                json=body,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
    except AbortedError:
        raise
    except httpx.TimeoutException as exc:
        raise ProviderError("provider request timed out") from exc
    except httpx.HTTPError as exc:
        raise ProviderError("provider transport unavailable") from exc

    _check_aborted(signal)
    if resp.status_code in (401, 403):
        raise ProviderError("provider authentication failed")
    if resp.status_code == 429:
        raise ProviderError("provider rate limited")
    if resp.status_code >= 400:
        raise ProviderError(f"provider request failed (HTTP {resp.status_code})")
    try:
        data = resp.json()
    except ValueError as exc:
        raise ProviderError("provider response could not be parsed") from exc
    if not isinstance(data, dict):
        raise ProviderError("provider response could not be parsed")
    return data


async def _tavily_search_execute(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
) -> AgentToolResult:
    del tool_call_id, on_update
    try:
        api_key = _env_required("TAVILY_API_KEY")
        args = _validate_search_params(params)
        payload: dict[str, Any] = {
            "query": args["query"],
            "topic": args["topic"],
            "search_depth": args["search_depth"],
            "max_results": args["max_results"],
            "include_raw_content": False,
            "include_domains": args["include_domains"],
        }
        if args["time_range"] != "any":
            payload["time_range"] = args["time_range"]
        data = await _post_json("/search", payload, api_key=api_key, signal=signal)
        normalized = normalize_search_hits(args["query"], data, max_results=args["max_results"])
        return _tool_result(normalized)
    except AbortedError:
        raise
    except ProviderError:
        raise
    except Exception as exc:  # noqa: BLE001 — sanitize
        raise ProviderError("provider request failed") from exc


async def _tavily_fetch_execute(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
) -> AgentToolResult:
    del tool_call_id, on_update
    try:
        api_key = _env_required("TAVILY_API_KEY")
        url = _validate_fetch_params(params)
        data = await _post_json("/extract", {"urls": [url]}, api_key=api_key, signal=signal)
        normalized = normalize_fetch(url, data)
        return _tool_result(normalized)
    except AbortedError:
        raise
    except ProviderError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ProviderError("provider request failed") from exc


def register(api: Any) -> None:
    # Fail closed before add_tool (F-S11)
    _env_required("TAVILY_API_KEY")
    api.add_tool(
        AgentTool(
            name="tavily_search",
            description="Search the web via Tavily. Returns search_result.v1 JSON.",
            parameters=_SEARCH_PARAMS,
            label="Tavily Search",
            execute=_tavily_search_execute,
            executionMode="parallel",
        )
    )
    api.add_tool(
        AgentTool(
            name="tavily_fetch",
            description="Extract full page content via Tavily. Returns fetch_result.v1 JSON.",
            parameters=_FETCH_PARAMS,
            label="Tavily Fetch",
            execute=_tavily_fetch_execute,
            executionMode="parallel",
        )
    )
