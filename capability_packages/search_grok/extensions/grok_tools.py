"""search_grok capability: grok_search AgentTool.

One-shot answer + hits (F-S5). Bounded retries only for this adapter (F-S12/F-S13).
Source split behavior aligned with GuDaStudio/GrokSearch (MIT) — thin rewrite, no vendor.
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import random
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from earendil_works.pi_agent.types import AgentTool, AgentToolResult

_TIMEOUT = httpx.Timeout(connect=6.0, write=10.0, read=120.0, pool=None)
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
_MAX_RETRIES = 3  # initial + 3 = up to 4 attempts
_RETRY_MULTIPLIER = 1.0
_RETRY_MAX_WAIT = 10.0

_SEARCH_PARAMS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "query": {
            "type": "string",
            "description": "Non-empty self-contained natural-language search query",
        },
        "platform": {
            "type": "string",
            "description": "Optional platform focus e.g. Twitter, GitHub, Reddit",
            "default": "",
        },
    },
    "required": ["query"],
}

_SEARCH_PROMPT = """
# Core Instruction

1. User needs may be vague. Think divergently, infer intent from multiple angles, and leverage full conversation context to progressively clarify their true needs.
2. **Breadth-First Search**—Approach problems from multiple dimensions. Brainstorm 5+ perspectives and execute parallel searches for each. Consult as many high-quality sources as possible before responding.
3. **Depth-First Search**—After broad exploration, select ≥2 most relevant perspectives for deep investigation into specialized knowledge.
4. **Evidence-Based Reasoning & Traceable Sources**—Every claim must be followed by a citation (`citation_card` format). More credible sources strengthen arguments. If no references exist, remain silent.
5. Before responding, ensure full execution of Steps 1–4.

---

# Search Instruction

1. Think carefully before responding—anticipate the user's true intent to ensure precision.
2. Verify every claim rigorously to avoid misinformation.
3. Follow problem logic—dig deeper until clues are exhaustively clear.
4. Search in English first (prioritizing English resources for volume/quality), but switch to Chinese if context demands.
5. Prioritize authoritative sources: Wikipedia, academic databases, books, reputable media/journalism.
6. Favor sharing in-depth, specialized knowledge over generic or common-sense content.

---

# Output Style

0. **Be direct—no unnecessary follow-ups**.
1. Lead with the **most probable solution** before detailed analysis.
2. **Define every technical term** in plain language.
3. Explain expertise **simply yet profoundly**.
4. **Respect facts and search results**.
5. **Every sentence must cite sources** (`citation_card`). More references = stronger credibility.
6. Expand on key concepts with real-world analogies when helpful.
7. **Strictly format outputs in polished Markdown**.
"""

_URL_PATTERN = re.compile(r'https?://[^\s<>"\'`，。、；：！？》）】\)]+')
_MD_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_SOURCES_HEADING_PATTERN = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]+|(?:[-*]|\d+\.)[ \t]+)?(?:\*\*|__)?\s*"
    r"(sources?|references?|citations?|信源|参考资料|参考|引用|来源列表|来源)"
    r"\s*(?:\*\*|__)?"
    r"(?:\s*[（(][^)\n]*[)）])?"
    r"\s*[:：]?\s*$"
)
_SOURCES_FUNCTION_PATTERN = re.compile(
    r"(?im)(^|\n)\s*(sources|source|citations|citation|references|reference|"
    r"citation_card|source_cards|source_card)\s*\("
)


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


def _local_time_info() -> str:
    try:
        local_now = datetime.now().astimezone()
    except Exception:  # noqa: BLE001
        local_now = datetime.now(timezone.utc)
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday = weekdays[local_now.weekday()]
    return f"Current local time: {local_now.isoformat()} ({weekday})\n"


def extract_unique_urls(text: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for m in _URL_PATTERN.finditer(text or ""):
        url = m.group().rstrip(".,;:!?")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _normalize_sources(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, (list, tuple)):
        items = list(data)
    elif isinstance(data, dict):
        items = [data]
    else:
        items = [data]
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            for url in extract_unique_urls(item):
                if url not in seen:
                    seen.add(url)
                    normalized.append({"url": url})
            continue
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            title, url = item[0], item[1]
            if isinstance(url, str) and url.startswith(("http://", "https://")) and url not in seen:
                seen.add(url)
                out: dict[str, Any] = {"url": url}
                if isinstance(title, str) and title.strip():
                    out["title"] = title.strip()
                normalized.append(out)
            continue
        if isinstance(item, dict):
            url = item.get("url") or item.get("href") or item.get("link")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                continue
            if url in seen:
                continue
            seen.add(url)
            out = {"url": url}
            title = item.get("title") or item.get("name") or item.get("label")
            if isinstance(title, str) and title.strip():
                out["title"] = title.strip()
            desc = item.get("description") or item.get("snippet") or item.get("content")
            if isinstance(desc, str) and desc.strip():
                out["description"] = desc.strip()
            normalized.append(out)
    return normalized


def _extract_sources_from_text(text: str) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for title, url in _MD_LINK_PATTERN.findall(text or ""):
        url = (url or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        title = (title or "").strip()
        sources.append({"title": title, "url": url} if title else {"url": url})
    for url in extract_unique_urls(text or ""):
        if url in seen:
            continue
        seen.add(url)
        sources.append({"url": url})
    return sources


def _parse_sources_payload(payload: str) -> list[dict[str, Any]]:
    payload = (payload or "").strip().rstrip(";")
    if not payload:
        return []
    data: Any = None
    try:
        data = json.loads(payload)
    except Exception:  # noqa: BLE001
        try:
            data = ast.literal_eval(payload)
        except Exception:  # noqa: BLE001
            data = None
    if data is None:
        return _extract_sources_from_text(payload)
    if isinstance(data, dict):
        for key in ("sources", "citations", "references", "urls"):
            if key in data:
                return _normalize_sources(data[key])
        return _normalize_sources(data)
    return _normalize_sources(data)


def _extract_balanced_call_at_end(text: str, open_paren_idx: int) -> tuple[int, str] | None:
    if open_paren_idx < 0 or open_paren_idx >= len(text) or text[open_paren_idx] != "(":
        return None
    depth = 1
    in_string: str | None = None
    escape = False
    for idx in range(open_paren_idx + 1, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == in_string:
                in_string = None
            continue
        if ch in ("'", '"'):
            in_string = ch
            continue
        if ch == "(":
            depth += 1
            continue
        if ch == ")":
            depth -= 1
            if depth == 0:
                if text[idx + 1 :].strip():
                    return None
                return idx, text[open_paren_idx + 1 : idx]
    return None


def _split_function_call_sources(text: str) -> tuple[str, list[dict[str, Any]]] | None:
    matches = list(_SOURCES_FUNCTION_PATTERN.finditer(text))
    if not matches:
        return None
    for m in reversed(matches):
        open_paren_idx = m.end() - 1
        extracted = _extract_balanced_call_at_end(text, open_paren_idx)
        if not extracted:
            continue
        _, args_text = extracted
        sources = _parse_sources_payload(args_text)
        if not sources:
            continue
        return text[: m.start()].rstrip(), sources
    return None


def _split_heading_sources(text: str) -> tuple[str, list[dict[str, Any]]] | None:
    matches = list(_SOURCES_HEADING_PATTERN.finditer(text))
    if not matches:
        return None
    for m in reversed(matches):
        sources = _extract_sources_from_text(text[m.start() :])
        if not sources:
            continue
        return text[: m.start()].rstrip(), sources
    return None


def _is_link_only_line(line: str) -> bool:
    stripped = re.sub(r"^\s*(?:[-*]|\d+\.)\s*", "", line).strip()
    if not stripped:
        return False
    if stripped.startswith(("http://", "https://")):
        return True
    return bool(_MD_LINK_PATTERN.search(stripped))


def _split_tail_link_block(text: str) -> tuple[str, list[dict[str, Any]]] | None:
    lines = text.splitlines()
    if not lines:
        return None
    idx = len(lines) - 1
    while idx >= 0 and not lines[idx].strip():
        idx -= 1
    if idx < 0:
        return None
    tail_end = idx
    link_like_count = 0
    while idx >= 0:
        line = lines[idx].strip()
        if not line:
            idx -= 1
            continue
        if not _is_link_only_line(line):
            break
        link_like_count += 1
        idx -= 1
    if link_like_count < 2:
        return None
    tail_start = idx + 1
    sources = _extract_sources_from_text("\n".join(lines[tail_start : tail_end + 1]))
    if not sources:
        return None
    return "\n".join(lines[:tail_start]).rstrip(), sources


def _split_details_block_sources(text: str) -> tuple[str, list[dict[str, Any]]] | None:
    lower = text.lower()
    close_idx = lower.rfind("</details>")
    if close_idx == -1:
        return None
    if text[close_idx + len("</details>") :].strip():
        return None
    open_idx = lower.rfind("<details", 0, close_idx)
    if open_idx == -1:
        return None
    sources = _extract_sources_from_text(text[open_idx : close_idx + len("</details>")])
    if len(sources) < 2:
        return None
    return text[:open_idx].rstrip(), sources


def split_answer_and_sources(text: str) -> tuple[str, list[dict[str, Any]]]:
    raw = (text or "").strip()
    if not raw:
        return "", []
    for splitter in (
        _split_function_call_sources,
        _split_heading_sources,
        _split_details_block_sources,
        _split_tail_link_block,
    ):
        split = splitter(raw)
        if split:
            return split
    return raw, []


def normalize_grok_result(query: str, raw_text: str) -> dict[str, Any]:
    answer, sources = split_answer_and_sources(raw_text)
    warnings: list[dict[str, str]] = []
    hits: list[dict[str, Any]] = []
    for src in sources:
        url = str(src.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        title = str(src.get("title") or "").strip() or url
        snippet = str(src.get("description") or src.get("snippet") or "")
        hits.append(
            {
                "rank": len(hits) + 1,
                "title": title,
                "url": url,
                "canonical_url": url,
                "snippet": snippet,
                "score": None,
                "published_at": None,
            }
        )
    if answer and not hits:
        warnings.append(_warning("sources_unavailable", "Grok answer present but no sources extracted"))
    if not answer and not hits:
        raise ProviderError("provider returned empty search result")
    return {
        "schema_version": "search_result.v1",
        "provider": "grok",
        "query": query,
        "answer": answer or None,
        "hits": hits,
        "warnings": warnings,
    }


def _validate_search_params(params: dict[str, Any]) -> dict[str, str]:
    if not isinstance(params, dict):
        raise ProviderError("invalid arguments")
    extra = set(params) - {"query", "platform"}
    if extra:
        raise ProviderError(f"unexpected properties: {sorted(extra)}")
    query = params.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ProviderError("query must be a non-empty string")
    platform = params.get("platform", "")
    if platform is None:
        platform = ""
    if not isinstance(platform, str):
        raise ProviderError("platform must be a string")
    return {"query": query.strip(), "platform": platform}


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return False


def _parse_retry_after(response: httpx.Response) -> float | None:
    header = response.headers.get("Retry-After")
    if not header:
        return None
    header = header.strip()
    try:
        return max(0.0, float(header))
    except ValueError:
        pass
    try:
        retry_dt = parsedate_to_datetime(header)
        if retry_dt.tzinfo is None:
            retry_dt = retry_dt.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_dt - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def _backoff_seconds(attempt: int, exc: BaseException | None) -> float:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        ra = _parse_retry_after(exc.response)
        if ra is not None:
            return ra
    # exponential with jitter, cap at _RETRY_MAX_WAIT
    base = min(_RETRY_MAX_WAIT, _RETRY_MULTIPLIER * (2**attempt))
    return min(_RETRY_MAX_WAIT, base * (0.5 + random.random()))


async def _sleep_abortable(seconds: float, signal: Any) -> None:
    end = asyncio.get_running_loop().time() + max(0.0, seconds)
    while True:
        _check_aborted(signal)
        remaining = end - asyncio.get_running_loop().time()
        if remaining <= 0:
            return
        await asyncio.sleep(min(0.1, remaining))


async def _parse_streaming_response(response: httpx.Response) -> str:
    content = ""
    full_body_buffer: list[str] = []
    async for line in response.aiter_lines():
        line = line.strip()
        if not line:
            continue
        full_body_buffer.append(line)
        if line.startswith("data:"):
            if line in ("data: [DONE]", "data:[DONE]"):
                continue
            try:
                data = json.loads(line[5:].lstrip())
            except json.JSONDecodeError:
                continue
            choices = data.get("choices") if isinstance(data, dict) else None
            if isinstance(choices, list) and choices:
                delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
                if isinstance(delta, dict) and "content" in delta:
                    content += str(delta.get("content") or "")
    if not content and full_body_buffer:
        try:
            data = json.loads("".join(full_body_buffer))
            if isinstance(data, dict):
                choices = data.get("choices") or []
                if choices and isinstance(choices[0], dict):
                    message = choices[0].get("message") or {}
                    if isinstance(message, dict):
                        content = str(message.get("content") or "")
        except json.JSONDecodeError:
            pass
    return content


async def _stream_chat_completion(
    *,
    api_url: str,
    api_key: str,
    model: str,
    query: str,
    platform: str,
    signal: Any,
) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    platform_prompt = ""
    if platform:
        platform_prompt = (
            "\n\nYou should search the web for the information you need, and focus on these platform: "
            + platform
            + "\n"
        )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SEARCH_PROMPT},
            {"role": "user", "content": _local_time_info() + query + platform_prompt},
        ],
        "stream": True,
    }
    endpoint = f"{api_url.rstrip('/')}/chat/completions"
    last_exc: BaseException | None = None
    for attempt in range(_MAX_RETRIES + 1):
        _check_aborted(signal)
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
                _check_aborted(signal)
                async with client.stream("POST", endpoint, headers=headers, json=payload) as response:
                    if response.status_code >= 400:
                        # read body discarded; raise status for retry logic
                        await response.aread()
                        raise httpx.HTTPStatusError(
                            f"HTTP {response.status_code}",
                            request=response.request,
                            response=response,
                        )
                    # First valid stream started — do not retry after chunks begin
                    text = await _parse_streaming_response(response)
                    if not text.strip():
                        raise ProviderError("provider returned empty search result")
                    return text
        except AbortedError:
            raise
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if not _is_retryable(exc) or attempt >= _MAX_RETRIES:
                if isinstance(exc, httpx.HTTPStatusError):
                    code = exc.response.status_code
                    if code in (401, 403):
                        raise ProviderError("provider authentication failed") from exc
                    if code == 429:
                        raise ProviderError("provider rate limited") from exc
                    raise ProviderError(f"provider request failed (HTTP {code})") from exc
                if isinstance(exc, httpx.TimeoutException):
                    raise ProviderError("provider request timed out") from exc
                if isinstance(exc, httpx.HTTPError):
                    raise ProviderError("provider transport unavailable") from exc
                raise ProviderError("provider request failed") from exc
            await _sleep_abortable(_backoff_seconds(attempt, exc), signal)
    raise ProviderError("provider request failed") from last_exc


async def _grok_search_execute(
    tool_call_id: str,
    params: dict[str, Any],
    signal: Any = None,
    on_update: Any = None,
) -> AgentToolResult:
    del tool_call_id, on_update
    try:
        api_key = _env_required("GROK_API_KEY")
        api_url = _env_required("GROK_API_URL")
        model = _env_required("GROK_MODEL")
        args = _validate_search_params(params)
        raw = await _stream_chat_completion(
            api_url=api_url,
            api_key=api_key,
            model=model,
            query=args["query"],
            platform=args["platform"],
            signal=signal,
        )
        return _tool_result(normalize_grok_result(args["query"], raw))
    except AbortedError:
        raise
    except ProviderError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ProviderError("provider request failed") from exc


def register(api: Any) -> None:
    _env_required("GROK_API_KEY")
    _env_required("GROK_API_URL")
    _env_required("GROK_MODEL")
    api.registerTool(AgentTool(
        name="grok_search",
        description=(
            "AI web search via Grok. Returns search_result.v1 with answer and source hits in one call."
        ),
        parameters=_SEARCH_PARAMS,
        label="Grok Search",
        execute=_grok_search_execute,
        executionMode="parallel",
    ))
