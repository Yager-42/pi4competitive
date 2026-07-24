"""search_anysearch capability: anysearch_search + anysearch_fetch AgentTools.

Uses a minimal in-process MCP streamable-HTTP client against ANYSEARCH_API_URL.
Exterior remains AgentTool only (no Pi MCP package type).
"""
from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

import httpx

from earendil_works.pi_agent.types import AgentTool, AgentToolResult

_TIMEOUT = httpx.Timeout(connect=6.0, write=10.0, read=120.0, pool=None)
_PROTOCOL_VERSION = "2024-11-05"

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
        "vertical": {
            "type": "string",
            "description": "web | news",
            "default": "web",
            "enum": ["web", "news"],
        },
        "freshness": {
            "type": "string",
            "description": "any | day | week | month | year",
            "default": "any",
            "enum": ["any", "day", "week", "month", "year"],
        },
        "country": {
            "type": ["string", "null"],
            "description": "ISO-3166 alpha-2 uppercase or null",
            "default": None,
        },
        "language": {
            "type": "string",
            "description": "zh | en",
            "default": "en",
            "enum": ["zh", "en"],
        },
        "include_domains": {
            "type": "array",
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

_MD_TITLE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_MD_SOURCE = re.compile(r"^\*\*Source\*\*:\s+(\S+)\s*$", re.MULTILINE)
_MD_RESULT_HEADING = re.compile(r"^###\s+\d+\.\s+(.+?)\s*$", re.MULTILINE)
_MD_URL_LINE = re.compile(r"^\s*-\s+\*\*URL\*\*:\s+(\S+)\s*$", re.MULTILINE)
_MD_BULLET = re.compile(r"^\s*-\s+(?!\*\*URL\*\*:)(.+)$", re.MULTILINE)


class ProviderError(RuntimeError):
    """Sanitized provider/config failure."""


class AbortedError(RuntimeError):
    """Propagated abort."""


def _env_required(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise ProviderError(f"missing required env: {name}")
    return value


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
    return value if isinstance(value, str) else default


def _parse_anysearch_markdown_search(text: str) -> list[dict[str, str]]:
    """Parse AnySearch MCP text results (### N. title / - **URL**: ...)."""
    items: list[dict[str, str]] = []
    parts = re.split(r"(?m)^(?=###\s+\d+\.\s+)", text)
    for part in parts:
        hm = _MD_RESULT_HEADING.search(part)
        um = _MD_URL_LINE.search(part)
        if not hm or not um:
            continue
        title = hm.group(1).strip()
        url = um.group(1).strip()
        snippet = ""
        for bm in _MD_BULLET.finditer(part):
            candidate = bm.group(1).strip()
            if candidate:
                snippet = candidate
                break
        items.append({"title": title, "url": url, "snippet": snippet})
    if items:
        return items
    # Legacy: "## title\n**Source**: url"
    legacy: list[dict[str, str]] = []
    chunks = re.split(r"\n(?=##\s)", text)
    for chunk in chunks:
        tm = _MD_TITLE.search(chunk)
        sm = _MD_SOURCE.search(chunk)
        if not tm or not sm:
            continue
        snip = ""
        for line in chunk.splitlines():
            if line.startswith("##") or line.startswith("**Source**"):
                continue
            if line.strip():
                snip = line.strip()
                break
        legacy.append({"title": tm.group(1), "url": sm.group(1), "snippet": snip})
    return legacy


def _parse_mcp_payload(result: Any) -> dict[str, Any] | None:
    """Extract structured dict from MCP tools/call result shapes."""
    if isinstance(result, dict):
        if result.get("isError"):
            raise ProviderError("provider tool returned error")
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        content = result.get("content")
        if isinstance(content, list):
            texts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(_as_str(block.get("text")))
            joined = "\n".join(t for t in texts if t)
            if joined:
                try:
                    parsed = json.loads(joined)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    title_m = _MD_TITLE.search(joined)
                    source_m = _MD_SOURCE.search(joined)
                    parts = re.split(r"^---\s*$", joined, maxsplit=1, flags=re.MULTILINE)
                    if title_m and source_m and len(parts) == 2 and parts[1].strip():
                        return {
                            "title": title_m.group(1),
                            "url": source_m.group(1),
                            "content": parts[1].strip(),
                        }
                    url_m = _MD_URL_LINE.search(joined)
                    head_m = re.search(r"^#\s+(.+?)\s*$", joined, re.MULTILINE)
                    if url_m and head_m:
                        return {
                            "title": head_m.group(1).strip(),
                            "url": url_m.group(1).strip(),
                            "content": joined,
                        }
                    items = _parse_anysearch_markdown_search(joined)
                    if items:
                        return {"results": items}
                    if joined.strip() and "Search Results" not in joined[:120]:
                        return {"title": "", "url": "", "content": joined}
    return None


def normalize_search(
    query: str,
    data: dict[str, Any],
    *,
    max_results: int,
) -> dict[str, Any]:
    warnings: list[dict[str, str]] = []
    items = data.get("results")
    if not isinstance(items, list):
        raise ProviderError("provider response could not be parsed")
    hits: list[dict[str, Any]] = []
    rejected = 0
    for item in items:
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
        snippet = _as_str(item.get("snippet") or item.get("description") or item.get("content"))
        score_raw = item.get("score")
        score = float(score_raw) if isinstance(score_raw, (int, float)) and not isinstance(score_raw, bool) else None
        published = item.get("published_at") or item.get("published_date")
        published_at = _as_str(published).strip() or None
        hits.append(
            {
                "rank": len(hits) + 1,
                "title": title,
                "url": url,
                "canonical_url": url,
                "snippet": snippet,
                "score": score,
                "published_at": published_at,
            }
        )
    if rejected:
        warnings.append(
            _warning("invalid_provider_item", "Some provider items could not be normalized")
        )
    return {
        "schema_version": "search_result.v1",
        "provider": "anysearch",
        "query": query,
        "answer": None,
        "hits": hits,
        "warnings": warnings,
    }


def normalize_fetch(url: str, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content") or data.get("text") or data.get("raw_content")
    if not isinstance(content, str) or not content.strip():
        raise ProviderError("fetch returned empty content")
    out_url = _as_str(data.get("url"), url).strip() or url
    title = _as_str(data.get("title")).strip()
    content_type = "markdown" if content.lstrip().startswith("#") else "text"
    return {
        "schema_version": "fetch_result.v1",
        "provider": "anysearch",
        "url": out_url,
        "canonical_url": out_url,
        "title": title,
        "content": content,
        "content_type": content_type,
        "warnings": [],
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
    vertical = params.get("vertical", "web")
    if vertical not in ("web", "news"):
        raise ProviderError("vertical must be web or news")
    freshness = params.get("freshness", "any")
    if freshness not in ("any", "day", "week", "month", "year"):
        raise ProviderError("freshness must be any|day|week|month|year")
    country = params.get("country", None)
    if country is not None:
        if not isinstance(country, str) or not re.fullmatch(r"[A-Z]{2}", country):
            raise ProviderError("country must be uppercase ISO-3166 alpha-2 or null")
    language = params.get("language", "en")
    if language not in ("zh", "en"):
        raise ProviderError("language must be zh or en")
    include_domains = params.get("include_domains", []) or []
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
        "vertical": vertical,
        "freshness": freshness,
        "country": country,
        "language": language,
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


def _decode_sse_or_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    # SSE: take last data: JSON object
    last: dict[str, Any] | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].lstrip()
        if not payload or payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            last = obj
    return last


async def _mcp_call_tool(
    *,
    endpoint: str,
    api_key: str,
    tool_name: str,
    arguments: dict[str, Any],
    signal: Any,
) -> dict[str, Any]:
    """Minimal streamable-HTTP MCP tools/call (initialize → call)."""
    _check_aborted(signal)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    req_id = 1

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        _check_aborted(signal)
        init_body = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "initialize",
            "params": {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "pi-search-anysearch", "version": "0.1.0"},
            },
        }
        try:
            init_resp = await client.post(endpoint, json=init_body, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderError("provider request timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("provider transport unavailable") from exc

        if init_resp.status_code in (401, 403):
            raise ProviderError("provider authentication failed")
        if init_resp.status_code == 429:
            raise ProviderError("provider rate limited")
        if init_resp.status_code >= 400:
            raise ProviderError(f"provider request failed (HTTP {init_resp.status_code})")

        session_id = init_resp.headers.get("mcp-session-id") or init_resp.headers.get("Mcp-Session-Id")
        call_headers = dict(headers)
        if session_id:
            call_headers["mcp-session-id"] = session_id

        # best-effort initialized notification (ignore failures)
        try:
            await client.post(
                endpoint,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=call_headers,
            )
        except httpx.HTTPError:
            pass

        _check_aborted(signal)
        call_body = {
            "jsonrpc": "2.0",
            "id": req_id + 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        try:
            call_resp = await client.post(endpoint, json=call_body, headers=call_headers)
        except httpx.TimeoutException as exc:
            raise ProviderError("provider request timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("provider transport unavailable") from exc

        if call_resp.status_code in (401, 403):
            raise ProviderError("provider authentication failed")
        if call_resp.status_code == 429:
            raise ProviderError("provider rate limited")
        if call_resp.status_code >= 400:
            raise ProviderError(f"provider request failed (HTTP {call_resp.status_code})")

        decoded = _decode_sse_or_json(call_resp.text)
        if not decoded:
            raise ProviderError("provider response could not be parsed")
        if "error" in decoded and decoded["error"]:
            raise ProviderError("provider tool returned error")
        result = decoded.get("result", decoded)
        payload = _parse_mcp_payload(result)
        if payload is None and isinstance(result, dict) and "results" in result:
            payload = result
        if payload is None:
            raise ProviderError("provider response could not be parsed")
        return payload


async def _anysearch_search_execute(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
) -> AgentToolResult:
    del tool_call_id, on_update
    try:
        api_key = _env_required("ANYSEARCH_API_KEY")
        endpoint = _env_required("ANYSEARCH_API_URL")
        args = _validate_search_params(params)
        upstream_args = {
            "query": args["query"],
            "max_results": args["max_results"],
            "include_domains": args["include_domains"],
            "freshness": args["freshness"],
            "country": args["country"],
            "language": args["language"],
            "vertical": args["vertical"],
        }
        data = await _mcp_call_tool(
            endpoint=endpoint,
            api_key=api_key,
            tool_name="search",
            arguments=upstream_args,
            signal=signal,
        )
        return _tool_result(normalize_search(args["query"], data, max_results=args["max_results"]))
    except AbortedError:
        raise
    except ProviderError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ProviderError("provider request failed") from exc


async def _anysearch_fetch_execute(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
) -> AgentToolResult:
    del tool_call_id, on_update
    try:
        api_key = _env_required("ANYSEARCH_API_KEY")
        endpoint = _env_required("ANYSEARCH_API_URL")
        url = _validate_fetch_params(params)
        data = await _mcp_call_tool(
            endpoint=endpoint,
            api_key=api_key,
            tool_name="extract",
            arguments={"url": url},
            signal=signal,
        )
        return _tool_result(normalize_fetch(url, data))
    except AbortedError:
        raise
    except ProviderError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ProviderError("provider request failed") from exc


def register(api: Any) -> None:
    _env_required("ANYSEARCH_API_KEY")
    _env_required("ANYSEARCH_API_URL")
    api.registerTool(AgentTool(
        name="anysearch_search",
        description="Search the web via AnySearch. Returns search_result.v1 JSON.",
        parameters=_SEARCH_PARAMS,
        label="AnySearch Search",
        execute=_anysearch_search_execute,
        executionMode="parallel",
    ))
    api.registerTool(AgentTool(
        name="anysearch_fetch",
        description="Extract full page content via AnySearch. Returns fetch_result.v1 JSON.",
        parameters=_FETCH_PARAMS,
        label="AnySearch Fetch",
        execute=_anysearch_fetch_execute,
        executionMode="parallel",
    ))


# silence unused import if tooling rewrites; uuid kept for future request ids
_ = uuid
