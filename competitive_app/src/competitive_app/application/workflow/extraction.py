"""Extraction intake — judge-based evidence extraction (research-workflow-v1 v0.2.0).

ADR 0010 D-S6/D-S7 / F-R29/F-R30. Replaces PR3/4's direct sub-agent-evidence
fill with judge LLM extraction: when a sub-agent's ``*_fetch`` tool returns a
page, the Extraction extension submits it to EvidenceIntake, which batches
observations and calls the judge LLM to extract (entity, attribute, value,
source, confidence) into the SOCM evidence graph + coverage map.

Judge: independent model (``JUDGE_MODEL`` env, default fallback to main model,
F-R29 — local reversal of F-R7). Called via raw ``models.streamSimple`` (no
harness — single "give text, want JSON" call). Batched: one judge call per
entity's empty cells (D-S6).

Hook: extension ``tool_result`` event (filter ``toolName in {*_fetch}``); the
subtask's target cells are read from a ContextVar set by the coverage engine
before the sub-agent prompt (D-S7). Buffered flush + sub-agent-exit drain.
"""
from __future__ import annotations

import contextvars
import json
import logging
import math
import time
from typing import Any
from uuid import uuid4

from ...domain.socm import EvidenceNode, SOCMState
from ...domain.socm.coverage import CellStatus
from .stage_outputs import model_name

_log = logging.getLogger(__name__)


async def _noop_emit(_event_type: str, _data: dict[str, Any]) -> None:
    """v0.3.1 SSE: default emit sink (no-op when SSE isn't wired)."""
    return


def _noop_journal_append(_event_type: str, _payload: dict[str, Any] | None = None) -> None:
    """Default journal sink (no-op when observability isn't wired)."""
    return


# ContextVar: the coverage engine sets this before a sub-agent prompt so the
# Extraction extension knows which entity + empty cells to extract for.
# Mirrors SearchOS set_current_table / _current_task_var (ADR 0010 D-S7).
current_subtask: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "extraction_current_subtask", default=None
)

# Cap judge input to avoid blowing the context window (ADR 0010 D-S7).
DEFAULT_JUDGE_MAX_INPUT_CHARS = 200_000


def _is_fetch_tool(tool_name: str) -> bool:
    return tool_name.endswith("_fetch")


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("content") or ""))
        return "".join(parts)
    if isinstance(content, dict):
        return str(content.get("text") or content.get("content") or "")
    return ""


def _try_parse_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except Exception:
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                return None
        return None


class EvidenceIntake:
    """Buffers page observations, batch-flushes via judge LLM into SOCM.

    PR5: simple synchronous flush (no background task pool yet — the sub-agent
    loop is single-threaded per harness, and ``flush`` is called at sub-agent
    exit). SearchOS uses a background flush semaphore; v0.2.0 keeps it inline
    for simplicity (F-R30 "buffer + batch flush" satisfied by per-entity batch).
    """

    def __init__(
        self,
        *,
        socm_store: Any,
        session_id: str,
        models: Any,
        judge_model: dict[str, Any] | None,
        max_input_chars: int = DEFAULT_JUDGE_MAX_INPUT_CHARS,
        emit_event: Any = None,
        journal_append: Any = None,
        task_id: str = "",
        extraction_skills: list[Any] | None = None,
    ) -> None:
        self._socm_store = socm_store
        self._session_id = session_id
        self._models = models
        self._judge_model = judge_model
        self._max_input_chars = max_input_chars
        self._task_id = task_id
        # v0.3.1 SSE: per-evidence event emit; no-op by default.
        self._emit_event = emit_event or _noop_emit
        self._journal_append = journal_append or _noop_journal_append
        self._extraction_skills = list(extraction_skills or [])[:3]
        self._buffer: dict[str, list[tuple[str, str]]] = {}

    def submit(self, entity_id: str, page_text: str, source: str) -> None:
        if not page_text or not entity_id:
            return
        self._buffer.setdefault(entity_id, []).append((page_text[: self._max_input_chars], source))

    async def flush(self) -> int:
        """Flush all buffered observations through the judge; fill SOCM.

        Returns the number of evidence nodes added. Called at sub-agent exit
        (drain point — F-R30 sub-agent-exit flush).
        """
        if not self._buffer:
            return 0
        added = 0
        for entity_id, observations in list(self._buffer.items()):
            added += await self._extract_entity(entity_id, observations)
        self._buffer.clear()
        return added

    async def _extract_entity(self, entity_id: str, observations: list[tuple[str, str]]) -> int:
        """Run the judge for one entity's empty cells against buffered pages."""
        # Load current SOCM to find this entity's empty cells.
        state = await self._socm_store.load(self._session_id)
        empty_attrs = [
            attr.id
            for cell in state.coverage_map.cells.values()
            if cell.entity_id == entity_id and cell.status == CellStatus.EMPTY
            for attr in state.coverage_map.attributes
            if attr.id == cell.attribute_id
        ]
        if not empty_attrs or not observations:
            # No empty cells left (already filled by a sibling) or no pages.
            return 0

        pages_blob = "\n\n---\n\n".join(f"[{i}] {src}\n{txt}" for i, (txt, src) in enumerate(observations))
        if len(pages_blob) > self._max_input_chars:
            pages_blob = pages_blob[: self._max_input_chars]
        findings = await self._call_judge(entity_id, empty_attrs, pages_blob)
        if not findings:
            return 0
        source_pages = {str(src).strip(): txt for txt, src in observations if str(src).strip()}

        added = 0
        emitted: list[dict[str, Any]] = []  # v0.3.1 SSE: collect evidence to emit after RMW

        def _fill(s: SOCMState) -> SOCMState:
            nonlocal added
            for item in findings:
                attr = str(item.get("attribute") or "")
                value = str(item.get("value") or "").strip()
                if not value or attr not in empty_attrs:
                    continue
                # A2: reject junk placeholder values — they mean "not found", not a real value.
                # Route these to UNKNOWN (mark_unknown) instead of FILLED so the cell stays
                # re-dispatchable and write renders it as "no reliable source".
                if _is_junk_value(value):
                    s.coverage_map.mark_unknown(entity_id, attr)
                    continue
                source = str(item.get("source") or "").strip()
                excerpt = str(item.get("source_excerpt") or "").strip()[:200]
                page_text = source_pages.get(source)
                if page_text is None or not excerpt or excerpt not in page_text:
                    # The judge may only cite pages actually fetched for this
                    # entity, and the quote must be verbatim evidence.
                    s.coverage_map.mark_unknown(entity_id, attr)
                    continue
                try:
                    raw_confidence = item.get("confidence")
                    confidence = float(raw_confidence) if raw_confidence is not None else 0.5
                except (TypeError, ValueError):
                    confidence = 0.5
                if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
                    s.coverage_map.mark_unknown(entity_id, attr)
                    continue
                # A2: low-confidence findings don't earn a FILLED — mark UNKNOWN so the
                # cell can be re-searched for a stronger source (Tier-0 judge fidelity).
                if confidence < _min_confidence():
                    s.coverage_map.mark_unknown(entity_id, attr)
                    continue
                node = EvidenceNode(
                    id=f"ev_{uuid4().hex[:8]}",
                    entity=entity_id,
                    attribute=attr,
                    value=value,
                    finding=f"{entity_id} {attr}: {value}",
                    source=source,
                    source_excerpt=excerpt,
                    confidence=confidence,
                )
                if s.evidence_graph.add_node(node):
                    s.coverage_map.fill(
                        entity_id, attr, value=value, source=source,
                        source_excerpt=excerpt, confidence=confidence,
                    )
                    added += 1
                    # v0.3.1 SSE: collect for emit after the RMW completes (can't await
                    # inside the synchronous atomic_update callback).
                    emitted.append({
                        "entity": entity_id, "attribute": attr, "value": value,
                        "source": source, "confidence": confidence,
                    })
            return s

        await self._socm_store.atomic_update(self._session_id, _fill)
        # v0.3.1 SSE: emit each evidence event (streamed, one per finding).
        for ev in emitted:
            await self._emit_event("evidence", ev)
        return added

    async def _call_judge(
        self, entity_id: str, empty_attrs: list[str], pages_blob: str
    ) -> list[dict[str, Any]]:
        """One-shot judge call via completeSimple; returns parsed findings."""
        prompt = _build_judge_prompt(entity_id, empty_attrs, pages_blob)
        if self._extraction_skills:
            from ..evolution.injector import compose_system_prompt
            prompt = compose_system_prompt(prompt, self._extraction_skills)
            self._journal_append(
                "skill.apply",
                {
                    "skill_ids": [s.skill_id or s.name for s in self._extraction_skills],
                    "entity": entity_id,
                    "task_id": self._task_id,
                },
            )
        context = {"messages": [{"role": "user", "content": prompt}]}
        t0 = time.monotonic()
        try:
            message = await self._models.completeSimple(self._judge_model, context)
        except Exception:  # noqa: BLE001
            _log.exception("judge completeSimple call failed for entity %s", entity_id)
            return []
        # v0.2.2 trace: record a span for the judge LLM call.
        usage = message.get("usage") if isinstance(message, dict) else None
        await self._emit_event(
            "span",
            {
                "kind": "judge", "stage": "search", "task_id": self._task_id,
                "entity": entity_id, "model": model_name(self._judge_model),
                "prompt_tokens": int((usage or {}).get("input", 0) or 0),
                "completion_tokens": int((usage or {}).get("output", 0) or 0),
                "latency_ms": int((time.monotonic() - t0) * 1000),
            },
        )
        text = _extract_assistant_text(message)
        if not text:
            return []
        parsed = _try_parse_json(text)
        if isinstance(parsed, list):
            return [p for p in parsed if isinstance(p, dict)]
        return []


def _extract_assistant_text(response: Any) -> str:
    """Pull text from a streamSimple response (list of events or message dict)."""
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        return _message_text(response.get("content"))
    if isinstance(response, list):
        # Event stream: find the final message_end / message event.
        for event in reversed(response):
            if not isinstance(event, dict):
                continue
            if event.get("type") in {"message_end", "message"}:
                msg = event.get("message") or event
                return _message_text(msg.get("content") if isinstance(msg, dict) else None)
            if event.get("type") == "text":
                return str(event.get("text") or "")
        return ""
    return ""


def _build_judge_prompt(entity_id: str, empty_attrs: list[str], pages_blob: str) -> str:
    attrs = ", ".join(empty_attrs)
    return (
        f"You are an evidence extraction judge. Given pages of fetched web content and a target "
        f"entity, extract structured findings for the entity's empty attribute cells.\n\n"
        f"Entity: {entity_id}\n"
        f"Attributes to fill: {attrs}\n\n"
        f"Pages:\n{pages_blob}\n\n"
        f"Return a JSON array of objects, one PER (attribute, source) pair — i.e. if the same "
        f"attribute is supported by multiple pages/sources, return one object for EACH source:\n"
        f'[{{"attribute": "<attr_id>", "value": "<value>", "source": "<url>", '
        f'"source_excerpt": "<verbatim quote>", "confidence": <0-1>}}]\n\n'
        f"STRICT RULES:\n"
        f"- Only fill an attribute if a page EXPLICITLY states its value with a verbatim quote. "
        f"If no page states the value, OMIT that attribute (do not include it in the array).\n"
        f"- NEVER return placeholder values: 'Not specified', 'N/A', 'n/a', 'Unknown', '未知', "
        f"'未公布', '暂未公布', 'TBD', '—', or any equivalent. If the page only implies or "
        f"guesses the value, OMIT the attribute.\n"
        f"- confidence reflects how directly + authoritatively the page supports the value "
        f"(official spec page = 0.9; reputable review = 0.7; forum/aggregator = 0.4).\n"
        f"- source_excerpt MUST be a verbatim substring of the page text supporting the value.\n"
        f"If no attribute can be filled from the pages, return []. Output ONLY the JSON array."
    )


# ----------------------------------------------------------- extension factory


def make_extraction_extension_factory(intake: EvidenceIntake):
    """Build an extension factory that hooks ``tool_result`` → EvidenceIntake.

    Returned callable is the ``register(api)`` function for load_extension_from_factory.
    Each ephemeral sub-agent harness gets its own intake (and thus its own buffer),
    so parallel sub-agents don't share extraction state.
    """

    def register(api) -> None:  # type: ignore[no-untyped-def]
        async def on_tool_result(event: dict[str, Any], _ctx: Any = None) -> None:
            tool_name = event.get("toolName") or event.get("tool_name") or ""
            if not _is_fetch_tool(str(tool_name)):
                return
            subtask = current_subtask.get()
            if not subtask:
                return
            entity_id = subtask.get("entity_id") or ""
            # The tool_result event carries content (list) + details (dict) at
            # top level (agent.py:494 emit). NOT nested under "result".
            page_text = _extract_page_text(event)
            source = _extract_source(event, tool_name)
            intake.submit(entity_id, page_text, source)

        api.on("tool_result", on_tool_result)

    return register


def _extract_page_text(event: Any) -> str:
    """Pull page text from a tool_result event (top-level content/details)."""
    if not isinstance(event, dict):
        return ""
    details = event.get("details")
    if isinstance(details, dict):
        for key in ("content", "text", "raw_content", "markdown"):
            val = details.get(key)
            if isinstance(val, str) and val:
                return val
        results = details.get("results")
        if isinstance(results, list):
            parts = []
            for item in results:
                if isinstance(item, dict):
                    parts.append(str(item.get("content") or item.get("raw_content") or ""))
            joined = "\n\n".join(p for p in parts if p)
            if joined:
                return joined
    content = event.get("content")
    if isinstance(content, list):
        return _message_text(content)
    if isinstance(content, str):
        return content
    return ""


def _extract_source(event: Any, tool_name: str) -> str:
    """Pull the source URL from a tool_result event."""
    if not isinstance(event, dict):
        return f"{tool_name}:fetch"
    details = event.get("details")
    if isinstance(details, dict):
        url = details.get("url") or details.get("source")
        if isinstance(url, str) and url:
            return url
        results = details.get("results")
        if isinstance(results, list) and results and isinstance(results[0], dict):
            url = results[0].get("url") or results[0].get("link")
            if isinstance(url, str):
                return url
    # Fall back to the tool input URL if present.
    inp = event.get("input")
    if isinstance(inp, dict):
        url = inp.get("url")
        if isinstance(url, str) and url:
            return url
    return f"{tool_name}:fetch"


# Junk placeholder patterns: a "value" matching these means the page did NOT state the
# value, so the cell should go UNKNOWN (re-searchable) rather than FILLED with garbage.
# ADR 0010 D-S6 fidelity fix (Tier-0): prevents "Not specified" / "N/A" poisoning cells.
_JUNK_PATTERNS = (
    "not specified",
    "not mentioned",
    "not available",
    "not stated",
    "not found",
    "not provided",
    "not yet",
    "no data",
    "no info",
    "no information",
    "n/a",
    "n a",
    "na",
    "unknown",
    "unspecified",
    "tbd",
    "tba",
    "pending",
    "placeholder",
    "see above",
    "未知",
    "未公布",
    "未提及",
    "未提供",
    "未明确",
    "暂未",
    "暂无",
    "暂未公布",
    "待定",
    "不详",
    "无数据",
    "尚无",
    "未见",
)


def _is_junk_value(value: str) -> bool:
    """True if `value` is a placeholder meaning "page didn't state it" (Tier-0).

    Normalized: lowercase, collapse whitespace, strip punctuation/dashes/quotes.
    A bare dash/underscore/dot or a pure number-free token like "N/A" matches.
    """
    import re

    norm = re.sub(r"[\s\-—–_\"'.,:;()]+", " ", value).strip().lower()
    if not norm:
        return True
    # Pure dash / dot / underscore / slash filler.
    if norm in {"-", "—", "–", "_", ".", "/", ":"}:
        return True
    return norm in _JUNK_PATTERNS


def _min_confidence() -> float:
    """SEARCH_MIN_CONFIDENCE env (default 0.4) — findings below this go UNKNOWN."""
    import os

    raw = os.environ.get("SEARCH_MIN_CONFIDENCE")
    if not raw:
        return 0.4
    try:
        return float(raw)
    except ValueError:
        return 0.4


__all__ = [
    "DEFAULT_JUDGE_MAX_INPUT_CHARS",
    "EvidenceIntake",
    "current_subtask",
    "make_extraction_extension_factory",
]
